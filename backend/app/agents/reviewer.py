# backend/app/agents/reviewer.py
# 作用：Reviewer Agent —— 审查 diff 与修改范围（FR-801 / FR-802）

import json
import logging
import re

from langchain_core.prompts import ChatPromptTemplate
from app.core.llm_trace import record_token_usage
from langchain_openai import ChatOpenAI

from app.core.config import get_settings
from app.schemas.review import ReviewIssue, ReviewResult

logger = logging.getLogger(__name__)

DANGEROUS_PATTERNS = (
    r"\beval\s*\(",
    r"\bexec\s*\(",
    r"os\.system\s*\(",
    r"subprocess\.(call|run|Popen)\s*\(",
    r"__import__\s*\(",
)
SENSITIVE_PATTERNS = (
    r"password\s*=",
    r"api_key\s*=",
    r"secret\s*=",
    r"token\s*=",
    r"AKIA[0-9A-Z]{16}",  # AWS key 前缀
)
CONFIG_PATH_HINTS = (
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "go.mod",
    "Cargo.toml",
    ".github/",
    "docker-compose",
    "Makefile",
)

SYSTEM_PROMPT = """你是 FixPilot 的 Reviewer Agent，审查代码修改 diff。

检查项：
1. 是否只修改计划内文件（scope creep）
2. 是否存在高风险代码（eval、exec、os.system 等）
3. 是否删除大量代码
4. 是否引入敏感信息（密码、token、密钥）
5. 是否修改配置、依赖或 CI
6. 是否有测试相关改动
7. 是否符合 issue 目标

风险等级：
- low：改动小、范围正确、无安全问题
- medium：有小问题但可接受
- high：越权修改、危险代码、敏感信息、严重偏离 issue

high 风险时 approval_required=true。

输出要求：只输出合法 JSON：
{{
  "risk_level": "low | medium | high",
  "review_comments": ["string"],
  "issues": [{{"type": "scope_creep", "message": "string", "file": "string或null"}}],
  "has_unauthorized_changes": false,
  "has_dangerous_code": false,
  "has_sensitive_info": false,
  "matches_issue_goal": true,
  "approval_required": false,
  "summary": "1-2句审查结论"
}}"""


def _extract_json_block(content: str) -> str:
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        end = -1 if lines[-1].strip() == "```" else len(lines)
        content = "\n".join(lines[1:end]).strip()
    start = content.find("{")
    end = content.rfind("}")
    if start != -1 and end != -1 and end > start:
        content = content[start : end + 1]
    return content


def _edited_paths(edit_history: list[dict]) -> set[str]:
    return {item["file_path"] for item in edit_history if item.get("file_path")}


def _count_deletions(diff: str | None) -> int:
    if not diff:
        return 0
    return sum(1 for line in diff.splitlines() if line.startswith("-") and not line.startswith("---"))


def review_diff_heuristic(
    allowed_files: list[str],
    edit_history: list[dict],
    current_diff: str | None,
    issue_text: str,
    plan: dict | None,
) -> ReviewResult:
    """规则审查兜底，不依赖 LLM。"""
    allowed_set = set(allowed_files)
    edited = _edited_paths(edit_history)
    unauthorized = edited - allowed_set

    diff = current_diff or ""
    comments: list[str] = []
    issues: list[ReviewIssue] = []

    for path in sorted(unauthorized):
        msg = f"修改了计划外文件：{path}"
        comments.append(msg)
        issues.append(ReviewIssue(type="scope_creep", message=msg, file=path))

    has_dangerous = any(re.search(p, diff, re.I) for p in DANGEROUS_PATTERNS)
    if has_dangerous:
        comments.append("diff 中包含潜在危险代码模式")
        issues.append(ReviewIssue(type="dangerous_code", message="检测到 eval/exec/subprocess 等模式"))

    has_sensitive = any(re.search(p, diff, re.I) for p in SENSITIVE_PATTERNS)
    if has_sensitive:
        comments.append("diff 中可能包含敏感信息")
        issues.append(ReviewIssue(type="sensitive_info", message="检测到 password/token/secret 等关键词"))

    config_touched = [p for p in edited if any(h in p for h in CONFIG_PATH_HINTS)]
    if config_touched:
        comments.append(f"改动了配置文件：{', '.join(config_touched)}")
        issues.append(
            ReviewIssue(type="config_change", message="修改了配置或依赖相关文件", file=config_touched[0])
        )

    deletions = _count_deletions(diff)
    if deletions > 80:
        comments.append(f"删除了较多代码行（约 {deletions} 行）")
        issues.append(ReviewIssue(type="large_deletion", message=f"大量删除约 {deletions} 行"))

    risk_level = "low"
    if unauthorized or has_dangerous or has_sensitive:
        risk_level = "high"
    elif config_touched or deletions > 80:
        risk_level = "medium"

    summary = "审查通过，未发现高风险问题。" if risk_level == "low" else "审查发现需关注的风险项。"
    if unauthorized:
        summary = "存在计划外文件修改，建议人工复核。"

    return ReviewResult(
        risk_level=risk_level,
        review_comments=comments,
        issues=issues,
        has_unauthorized_changes=bool(unauthorized),
        has_dangerous_code=has_dangerous,
        has_sensitive_info=has_sensitive,
        matches_issue_goal=True,
        approval_required=risk_level == "high",
        summary=summary,
    )


def review_diff(
    issue_text: str,
    plan: dict | None,
    allowed_files: list[str],
    edit_history: list[dict],
    current_diff: str | None,
    test_results: list[dict] | None = None,
) -> ReviewResult:
    """
    审查当前 diff（FR-801 / FR-802）。

    LLM 失败时回退启发式规则。
    """
    if not edit_history:
        return ReviewResult(
            risk_level="low",
            review_comments=["无代码修改记录"],
            summary="未产生 diff，跳过深度审查",
            matches_issue_goal=True,
        )

    plan_summary = (plan or {}).get("problem_summary", "")
    diff_excerpt = (current_diff or "")[:6000]
    edited_list = ", ".join(sorted(_edited_paths(edit_history)))
    test_summary = ""
    if test_results:
        passed = sum(1 for t in test_results if t.get("passed"))
        test_summary = f"测试记录 {passed}/{len(test_results)} 通过"

    user_prompt = f"""请审查以下修改：

## Issue
{issue_text[:2000]}

## 计划摘要
{plan_summary}

## 允许修改的文件
{allowed_files}

## 实际修改的文件
{edited_list}

## Git diff（节选）
{diff_excerpt or '（无）'}

## 测试情况
{test_summary or '未运行'}

请直接输出 JSON。"""

    settings = get_settings()
    llm = ChatOpenAI(
        model=settings.model_name,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        temperature=0,
        request_timeout=120,
        max_retries=2,
    )
    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("human", "{user_prompt}"),
    ])

    try:
        messages = prompt.format_messages(user_prompt=user_prompt)
        response = llm.invoke(messages)
        record_token_usage(response)
        data = json.loads(_extract_json_block(response.content))
        issues_raw = data.pop("issues", [])
        issues = [ReviewIssue(**item) for item in issues_raw]
        result = ReviewResult(**data, issues=issues)
        if result.risk_level == "high":
            result.approval_required = True
        return result
    except Exception as exc:
        logger.warning(f"Reviewer LLM 失败，使用启发式兜底：{exc}")
        return review_diff_heuristic(
            allowed_files, edit_history, current_diff, issue_text, plan
        )

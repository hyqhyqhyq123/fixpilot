# backend/app/agents/pr_writer.py
# 作用：PR Writer Agent —— 根据 diff 和审查结果生成 PR 文案（FR-901）

import json
import logging

from langchain_core.prompts import ChatPromptTemplate
from app.core.llm_trace import record_token_usage
from langchain_openai import ChatOpenAI

from app.core.config import get_settings
from app.schemas.pr_description import PRDescription

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是 FixPilot 的 PR Writer Agent，根据 issue、修改计划和 diff 生成 GitHub PR 描述。

要求：
- 标题简洁，用 conventional commits 风格（如 fix: ...）
- commit_message 必须是一行 Git 提交信息，使用 conventional commits 风格（如 fix: ...）
- Summary 说明为什么改
- Changes 列举具体改动
- Tests 说明如何验证
- Risks 说明潜在风险
- Notes 可选补充

输出要求：只输出合法 JSON：
{{
  "title": "string",
  "commit_message": "string",
  "summary": "markdown 段落",
  "changes": "markdown 列表",
  "tests": "markdown 段落",
  "risks": "markdown 段落",
  "notes": "string 或 null",
  "full_markdown": "完整 PR Markdown（含 ## Summary 等标题）"
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


def _clean_one_line(text: str) -> str:
    """把 LLM/issue 文本压成适合作为标题的一行。"""
    cleaned = " ".join((text or "").replace("\n", " ").split())
    return cleaned.strip(" #`\"'")


def build_commit_message(title: str | None, summary: str | None, issue_text: str) -> str:
    """生成 conventional commits 风格的一行 commit message。

    为什么单独做这个函数：
    - LLM 有时会漏字段，兜底逻辑要稳定。
    - commit message 会直接进入 `git commit -m`，必须短、单行、可读。
    """
    conventional_prefixes = (
        "fix:",
        "feat:",
        "docs:",
        "test:",
        "refactor:",
        "chore:",
        "style:",
        "perf:",
    )
    source = _clean_one_line(title or summary or issue_text or "FixPilot automated patch")
    lower_source = source.lower()

    for prefix in conventional_prefixes:
        if lower_source.startswith(prefix):
            return source[:100]

    hint_text = f"{summary or ''} {issue_text or ''}".lower()
    if any(word in hint_text for word in ("doc", "readme", "文档")):
        prefix = "docs"
    elif any(word in hint_text for word in ("test", "测试")):
        prefix = "test"
    elif any(word in hint_text for word in ("feature", "add", "新增", "添加")):
        prefix = "feat"
    elif any(word in hint_text for word in ("refactor", "重构")):
        prefix = "refactor"
    else:
        prefix = "fix"

    # 去掉常见前缀，避免出现 "fix: fix: xxx"。
    for existing in conventional_prefixes:
        if lower_source.startswith(existing):
            source = source[len(existing):].strip()
            break

    return f"{prefix}: {source[:90]}".strip()


def _build_full_markdown(pr: PRDescription) -> str:
    commit_message = pr.commit_message or build_commit_message(
        pr.title, pr.summary, pr.summary
    )
    if pr.full_markdown:
        if "## Commit Message" in pr.full_markdown:
            return pr.full_markdown
        return "\n".join(
            [
                "## Commit Message",
                "```text",
                commit_message,
                "```",
                "",
                pr.full_markdown,
            ]
        )
    parts = [
        f"# {pr.title}",
        "",
        "## Commit Message",
        "```text",
        commit_message,
        "```",
        "",
        "## Summary",
        pr.summary,
        "",
        "## Changes",
        pr.changes,
        "",
        "## Tests",
        pr.tests,
        "",
        "## Risks",
        pr.risks,
    ]
    if pr.notes:
        parts.extend(["", "## Notes", pr.notes])
    return "\n".join(parts)


def generate_pr_heuristic(
    issue_text: str,
    plan: dict | None,
    edit_history: list[dict],
    test_results: list[dict] | None,
    review_result: dict | None,
) -> PRDescription:
    """无 LLM 时的模板兜底。"""
    plan = plan or {}
    files = sorted({item.get("file_path", "") for item in edit_history if item.get("file_path")})
    changes_lines = "\n".join(f"- `{p}`" for p in files) if files else "- （无文件变更记录）"

    test_lines: list[str] = []
    if test_results:
        for item in test_results:
            status = "通过" if item.get("passed") else "失败"
            test_lines.append(f"- {item.get('check_type', 'test')}：{status} — `{item.get('command')}`")
    tests = "\n".join(test_lines) if test_lines else "请手动运行项目测试命令验证。"

    risk = (review_result or {}).get("risk_level", "low")
    risks = f"审查风险等级：**{risk}**。"
    if review_result and review_result.get("review_comments"):
        risks += "\n" + "\n".join(f"- {c}" for c in review_result["review_comments"])

    summary = plan.get("problem_summary") or issue_text[:300]
    title = f"fix: {summary[:60]}" if summary else "fix: issue repair"
    commit_message = build_commit_message(title, summary, issue_text)

    pr = PRDescription(
        title=title,
        commit_message=commit_message,
        summary=summary,
        changes=changes_lines,
        tests=tests,
        risks=risks,
        notes="由 FixPilot 自动生成，提交前请人工复核。",
    )
    pr.full_markdown = _build_full_markdown(pr)
    return pr


def generate_pr_description(
    issue_text: str,
    plan: dict | None,
    edit_history: list[dict],
    current_diff: str | None,
    test_results: list[dict] | None = None,
    review_result: dict | None = None,
) -> PRDescription:
    """生成 PR 文案（FR-901）。"""
    plan = plan or {}
    diff_excerpt = (current_diff or "")[:5000]
    review_summary = (review_result or {}).get("summary", "")

    user_prompt = f"""请为以下修复生成 PR 描述：

## Issue
{issue_text[:2000]}

## 问题摘要
{plan.get('problem_summary', '')}

## 修改文件
{[item.get('file_path') for item in edit_history]}

## Diff 节选
{diff_excerpt or '（无）'}

## 审查结论
{review_summary}

## 测试结果
{test_results or []}

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
        pr = PRDescription(**data)
        if not pr.commit_message:
            pr.commit_message = build_commit_message(pr.title, pr.summary, issue_text)
        pr.full_markdown = _build_full_markdown(pr)
        return pr
    except Exception as exc:
        logger.warning(f"PR Writer LLM 失败，使用模板兜底：{exc}")
        return generate_pr_heuristic(
            issue_text, plan, edit_history, test_results, review_result
        )

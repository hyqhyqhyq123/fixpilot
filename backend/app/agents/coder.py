# backend/app/agents/coder.py
# 作用：Coder Agent —— 根据已审批计划修改代码（FR-501 / FR-502 / FR-503）
#
# 流程：
# 1. 读取计划中允许修改的文件当前内容
# 2. LLM 生成完整文件内容（JSON）
# 3. edit_file_tool 写入并生成 diff
# 4. 失败时回滚已写入文件

import json
import logging

from langchain_core.prompts import ChatPromptTemplate
from app.core.llm_trace import record_token_usage
from langchain_openai import ChatOpenAI

from app.core.config import get_settings
from app.schemas.coder import CoderApplyResult, CoderOutput, FileEditOperation
from app.tools.edit_file_tool import edit_file, rollback_file
from app.tools.git_diff_tool import get_git_diff
from app.tools.read_file_tool import read_file

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是 FixPilot 的 Coder Agent，根据已审批的修改计划编写代码。

规则：
1. 只能修改 allowed_files 列表中的文件
2. 输出每个文件的**完整**修改后内容（不是 diff 片段）
3. 保持项目现有代码风格和缩进
4. 只做计划要求的修改，不要重构无关代码
5. 如果计划中包含测试文件，必须新增或更新该测试文件；若无法补测试，必须在 test_note 说明原因

输出要求：只输出一个合法 JSON，格式：
{{
  "edits": [
    {{
      "path": "相对仓库根目录路径",
      "content": "修改后的完整文件内容",
      "is_new_file": false
    }}
  ],
  "test_note": "未补测试时的原因，或 null"
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


def _parse_coder_output(raw_content: str) -> CoderOutput:
    json_str = _extract_json_block(raw_content)
    data = json.loads(json_str)
    edits = [FileEditOperation(**item) for item in data.get("edits", [])]
    return CoderOutput(edits=edits, test_note=data.get("test_note"))


TEST_DIR_NAMES = {"tests", "test", "__tests__", "spec"}


def _normalize_repo_path(path: str) -> str:
    return path.replace("\\", "/").strip("/")


def _is_test_path(path: str) -> bool:
    """判断路径是否像测试文件或测试目录。"""

    normalized = _normalize_repo_path(path)
    parts = normalized.split("/")
    if any(part in TEST_DIR_NAMES for part in parts):
        return True

    filename = parts[-1] if parts else normalized
    return bool(
        filename.startswith("test_")
        or filename.endswith("_test.py")
        or ".test." in filename
        or ".spec." in filename
        or filename.endswith("_test.go")
    )


def _planned_test_paths(plan: dict) -> set[str]:
    paths: set[str] = set()
    for key in ("files_to_modify", "files_to_add"):
        for item in plan.get(key) or []:
            path = item.get("path")
            if path and _is_test_path(path):
                paths.add(_normalize_repo_path(path))
    return paths


def _build_coder_context(
    plan: dict,
    allowed_files: list[str],
    repo_path: str,
    issue_text: str,
) -> str:
    """读取允许修改的文件内容，拼进 prompt。"""
    sections = [
        f"## Issue\n{issue_text}",
        f"## 问题摘要\n{plan.get('problem_summary', '')}",
        f"## 根因假设\n{plan.get('root_cause_hypothesis', '')}",
        "## 修改计划",
    ]

    for item in plan.get("files_to_modify", []):
        sections.append(
            f"- 修改 {item.get('path')}：{item.get('reason')}；"
            f"改动点：{'; '.join(item.get('planned_changes', []))}"
        )
    for item in plan.get("files_to_add", []):
        sections.append(
            f"- 新建 {item.get('path')}：{item.get('reason')}"
        )

    sections.append("\n## 允许修改的文件当前内容")
    for path in allowed_files:
        result = read_file(repo_path, path)
        if result.get("error"):
            sections.append(f"\n### {path}\n（读取失败：{result['error']}）")
            continue
        content = result["content"]
        if result.get("truncated"):
            content += "\n...（文件已截断，仅显示前 30KB）"
        sections.append(f"\n### {path}\n```\n{content}\n```")

    return "\n".join(sections)


def apply_approved_plan(
    repo_path: str,
    issue_text: str,
    plan: dict,
    allowed_files: list[str],
    retry_index: int = 0,
    failure_analysis: dict | None = None,
) -> CoderApplyResult:
    """
    根据已审批计划生成并应用代码修改。

    参数:
        repo_path: 仓库本地路径
        issue_text: 原始 issue
        plan: FixPlan dict
        allowed_files: 白名单路径列表
        retry_index: 第几次尝试（写入 edit_history 用）
    """
    logger.info(f"Coder 开始：repo={repo_path}, allowed={len(allowed_files)} 个文件")

    settings = get_settings()
    # Coder prompt 含多文件全文，生成耗时较长，需放宽超时并允许多次重试
    llm = ChatOpenAI(
        model=settings.model_name,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        temperature=0,
        request_timeout=300,
        max_retries=3,
    )

    context = _build_coder_context(plan, allowed_files, repo_path, issue_text)

    retry_section = ""
    if failure_analysis:
        hints = failure_analysis.get("retry_hints") or ""
        plans = failure_analysis.get("next_fix_plan") or []
        retry_section = f"""
## 上次测试失败诊断（请据此修复）
- 摘要：{failure_analysis.get('failure_summary', '')}
- 原因：{failure_analysis.get('likely_cause', '')}
- 建议：{'; '.join(plans)}
- 提示：{hints}

"""

    user_prompt = f"""请根据以下已审批计划修改代码。
{retry_section}
{context}

允许修改的文件（只能改这些）：{allowed_files}

请直接输出 JSON，不要有其他文字。"""

    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("human", "{user_prompt}"),
    ])

    try:
        messages = prompt.format_messages(user_prompt=user_prompt)
        response = llm.invoke(messages)
        record_token_usage(response)
        coder_output = _parse_coder_output(response.content)
    except Exception as exc:
        logger.error(f"Coder LLM 调用或解析失败：{exc}")
        return CoderApplyResult(
            success=False,
            error_message=f"Coder 生成失败：{exc}",
        )

    # 校验 LLM 输出的路径都在白名单内
    allowed_set = set(allowed_files)
    for edit in coder_output.edits:
        if edit.path not in allowed_set:
            return CoderApplyResult(
                success=False,
                error_message=f"Coder 试图修改计划外文件：{edit.path}",
            )

    planned_tests = _planned_test_paths(plan)
    edited_paths = {_normalize_repo_path(edit.path) for edit in coder_output.edits}
    edited_tests = {path for path in edited_paths if _is_test_path(path)}
    if planned_tests and not edited_tests and not coder_output.test_note:
        return CoderApplyResult(
            success=False,
            error_message=(
                "计划要求新增或更新测试文件，但 Coder 未返回测试文件修改，"
                "也没有在 test_note 说明原因"
            ),
        )

    applied: list[dict] = []
    edited_paths: list[str] = []

    try:
        for edit in coder_output.edits:
            result = edit_file(
                repo_path=repo_path,
                file_path=edit.path,
                new_content=edit.content,
                allowed_files=allowed_files,
                is_new_file=edit.is_new_file,
            )
            if not result["success"]:
                raise RuntimeError(result.get("error") or f"写入失败：{edit.path}")

            record = {
                "file_path": edit.path,
                "retry_index": retry_index,
                "before_content": result["before_content"],
                "after_content": result["after_content"],
                "diff": result["diff"],
            }
            applied.append(record)
            edited_paths.append(edit.path)

    except Exception as exc:
        # 回滚已成功写入的文件
        for record in reversed(applied):
            rollback_file(repo_path, record["file_path"], record["before_content"])
        return CoderApplyResult(
            success=False,
            edited_files=edited_paths,
            edit_records=applied,
            error_message=str(exc),
        )

    git_result = get_git_diff(repo_path)
    combined_diff = git_result.get("diff") or "\n".join(
        r.get("diff") or "" for r in applied
    )

    logger.info(f"Coder 完成：修改 {len(edited_paths)} 个文件")
    return CoderApplyResult(
        success=True,
        edited_files=edited_paths,
        edit_records=applied,
        combined_diff=combined_diff,
        test_note=coder_output.test_note,
    )

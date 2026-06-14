# backend/app/agents/failure_diagnoser.py
# 作用：Failure Diagnosis Agent —— 分析测试失败日志（FR-701）
#
# 输出结构化诊断，供 retry_decision_node 决定是否回到 Coder 重试。

import json
import logging

from langchain_core.prompts import ChatPromptTemplate
from app.core.llm_trace import record_token_usage
from langchain_openai import ChatOpenAI

from app.core.config import get_settings
from app.schemas.diagnosis import FailureDiagnosis

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是 FixPilot 的 Failure Diagnosis Agent，分析测试/lint/typecheck 失败日志。

职责：
1. 总结失败表现（failure_summary）
2. 推断最可能原因（likely_cause）
3. 判断失败是否由**当前这次代码修改**导致（is_caused_by_current_patch）
4. 给出下一步修复建议（next_fix_plan，每条一个具体动作）
5. 决定是否建议重试（should_retry）
6. 若应重试，给 Coder 的额外提示（retry_hints）

原则：
- 环境/依赖/网络问题 → is_caused_by_current_patch=false, should_retry=false
- 明显由本次 patch 引入的断言/语法错误 → should_retry=true
- 信息不足时保守：should_retry=false

输出要求：只输出合法 JSON：
{{
  "failure_summary": "string",
  "likely_cause": "string",
  "is_caused_by_current_patch": true,
  "next_fix_plan": ["string"],
  "should_retry": true,
  "retry_hints": "string"
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


def _failed_checks(test_results: list[dict]) -> list[dict]:
    return [item for item in test_results if not item.get("passed")]


def _build_log_excerpt(results: list[dict], limit: int = 4000) -> str:
    parts: list[str] = []
    for item in results:
        label = item.get("check_type", "test")
        parts.append(f"### {label}：{item.get('command')}")
        parts.append(f"exit_code={item.get('exit_code')}, passed={item.get('passed')}")
        if item.get("stderr"):
            parts.append(f"stderr:\n{item['stderr'][:limit]}")
        if item.get("stdout"):
            parts.append(f"stdout:\n{item['stdout'][:limit]}")
    return "\n".join(parts)


def diagnose_failure_heuristic(
    failed_results: list[dict],
    current_diff: str | None,
) -> FailureDiagnosis:
    """LLM 不可用时的规则兜底，保证 workflow 可继续。"""
    combined = _build_log_excerpt(failed_results, limit=2000)
    env_keywords = (
        "docker",
        "connection refused",
        "module not found",
        "no module named",
        "command not found",
        "permission denied",
    )
    lower = combined.lower()
    is_env = any(k in lower for k in env_keywords)

    first_cmd = failed_results[0].get("command", "unknown")
    summary = f"检查失败：{first_cmd}（共 {len(failed_results)} 项未通过）"

    if is_env:
        return FailureDiagnosis(
            failure_summary=summary,
            likely_cause="疑似环境或依赖问题，而非业务逻辑断言失败",
            is_caused_by_current_patch=False,
            next_fix_plan=["检查 Docker 镜像、依赖安装与测试命令是否正确"],
            should_retry=False,
            retry_hints="",
        )

    has_diff = bool(current_diff and current_diff.strip())
    return FailureDiagnosis(
        failure_summary=summary,
        likely_cause="测试/lint 未通过，可能与本次修改相关",
        is_caused_by_current_patch=has_diff,
        next_fix_plan=[
            "根据 stderr/stdout 定位失败断言或语法问题",
            "在 allowed_files 内做最小修复",
        ],
        should_retry=has_diff,
        retry_hints=combined[:1500],
    )


def diagnose_test_failure(
    issue_text: str,
    plan: dict | None,
    test_results: list[dict],
    current_diff: str | None,
    retry_count: int = 0,
) -> FailureDiagnosis:
    """
    分析测试失败并返回结构化诊断（FR-701）。

    LLM 失败时回退到启发式规则，避免阻断 workflow。
    """
    failed = _failed_checks(test_results)
    if not failed:
        return FailureDiagnosis(
            failure_summary="无失败检查项",
            likely_cause="状态不一致：诊断节点被调用但没有失败结果",
            is_caused_by_current_patch=False,
            next_fix_plan=[],
            should_retry=False,
            retry_hints="",
        )

    log_excerpt = _build_log_excerpt(failed)
    plan_summary = (plan or {}).get("problem_summary", "")
    diff_excerpt = (current_diff or "")[:3000]

    user_prompt = f"""请分析以下测试失败（当前第 {retry_count} 次重试后）：

## Issue
{issue_text[:2000]}

## 计划摘要
{plan_summary}

## 当前 diff（节选）
{diff_excerpt or '（无 diff）'}

## 失败日志
{log_excerpt}

请直接输出 JSON，不要有其他文字。"""

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
        return FailureDiagnosis(**data)
    except Exception as exc:
        logger.warning(f"Failure Diagnosis LLM 失败，使用启发式兜底：{exc}")
        return diagnose_failure_heuristic(failed, current_diff)

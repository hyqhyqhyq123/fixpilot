# backend/app/agents/task_judge.py
# LLM-as-Judge：对已完成任务做自动评测（Phase 6）

from __future__ import annotations

import json
import logging

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from app.core.config import get_settings
from app.core.llm_trace import record_token_usage

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是 FixPilot 的任务评测 Judge（LLM-as-Judge）。

根据 issue、修改计划、diff、测试结果与最终报告，对修复任务打分（0-100 整数）。

评分维度：
- plan_score：修改计划是否合理、范围是否恰当
- patch_score：patch 是否针对 issue、改动质量如何
- test_score：测试是否运行、是否通过、是否覆盖改动
- overall_score：综合修复是否成功（加权：patch 40% + plan 25% + test 35%）

输出要求：只输出合法 JSON：
{{
  "overall_score": 0,
  "patch_score": 0,
  "plan_score": 0,
  "test_score": 0,
  "judge_summary": "1-3 句结论",
  "strengths": ["string"],
  "weaknesses": ["string"],
  "recommendations": ["string"]
}}"""


def _extract_json_block(content: str) -> str:
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        end = -1 if lines[-1].strip() == "```" else len(lines)
        content = "\n".join(lines[1:end]).strip()
    start = content.find("{")
    end = content.rfind("}")
    if start >= 0 and end > start:
        return content[start : end + 1]
    return content


def _clamp_score(value: object) -> int:
    try:
        score = int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, score))


def judge_task_result(context: str) -> dict:
    """调用 LLM 对任务上下文打分。"""
    settings = get_settings()
    llm = ChatOpenAI(
        model=settings.model_name,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        temperature=0,
    )
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT),
            ("human", "请评测以下任务：\n\n{context}"),
        ]
    )
    chain = prompt | llm
    response = chain.invoke({"context": context})
    record_token_usage(response)

    raw = response.content if isinstance(response.content, str) else str(response.content)
    data = json.loads(_extract_json_block(raw))

    return {
        "overall_score": _clamp_score(data.get("overall_score")),
        "patch_score": _clamp_score(data.get("patch_score")),
        "plan_score": _clamp_score(data.get("plan_score")),
        "test_score": _clamp_score(data.get("test_score")),
        "judge_summary": str(data.get("judge_summary") or "评测完成"),
        "details": {
            "strengths": data.get("strengths") or [],
            "weaknesses": data.get("weaknesses") or [],
            "recommendations": data.get("recommendations") or [],
        },
    }

# backend/app/core/llm_trace.py
# 作用：从 LangChain LLM 响应中提取 token 用量，供 Agent Trace 展示。
#
# 为什么用 ContextVar？
# Node 函数返回 State 更新字段，不想让每个 Agent 改返回值结构；
# 因此在 invoke 后写入上下文，workflow_runner 在 _run_node 末尾读取。

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

_trace_token_usage: ContextVar[dict[str, int] | None] = ContextVar(
    "trace_token_usage",
    default=None,
)


def extract_token_usage(response: Any) -> dict[str, int] | None:
    """从 LangChain AIMessage 提取 prompt/completion/total tokens。"""
    usage: dict[str, int] = {}

    meta = getattr(response, "usage_metadata", None)
    if isinstance(meta, dict):
        for src, dst in (
            ("input_tokens", "prompt_tokens"),
            ("output_tokens", "completion_tokens"),
            ("total_tokens", "total_tokens"),
        ):
            val = meta.get(src)
            if isinstance(val, int):
                usage[dst] = val

    legacy = getattr(response, "response_metadata", None) or {}
    token_usage = legacy.get("token_usage") if isinstance(legacy, dict) else None
    if isinstance(token_usage, dict):
        for src, dst in (
            ("prompt_tokens", "prompt_tokens"),
            ("completion_tokens", "completion_tokens"),
            ("total_tokens", "total_tokens"),
        ):
            val = token_usage.get(src)
            if isinstance(val, int):
                usage[dst] = val

    return usage or None


def record_token_usage(response: Any) -> dict[str, int] | None:
    """解析并写入当前上下文，供 workflow_runner 读取。"""
    usage = extract_token_usage(response)
    if usage:
        _trace_token_usage.set(usage)
    return usage


def pop_token_usage() -> dict[str, int] | None:
    """读取并清空当前上下文的 token 用量。"""
    usage = _trace_token_usage.get()
    _trace_token_usage.set(None)
    return usage

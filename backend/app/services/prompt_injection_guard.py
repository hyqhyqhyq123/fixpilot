# backend/app/services/prompt_injection_guard.py
# 作用：在 RAG 上下文进入 LLM 前，检测并标记可疑 prompt injection。
#
# 为什么需要这个：
# - 代码仓库、README、issue 评论都可能包含“忽略之前指令”这类文本
# - RAG 会把检索到的片段塞进 Planner/Coder prompt
# - 如果不做隔离，LLM 可能把仓库里的恶意文本当成系统指令

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class PromptInjectionFinding:
    line_number: int
    severity: str
    rule_name: str
    excerpt: str


_PROMPT_INJECTION_RULES: list[tuple[str, str, re.Pattern[str]]] = [
    (
        "instruction_override",
        "high",
        re.compile(
            r"\b(ignore|disregard|forget|override)\b.{0,80}\b(previous|above|system|developer|instruction|prompt)s?\b",
            re.IGNORECASE,
        ),
    ),
    (
        "role_hijack",
        "high",
        re.compile(
            r"\b(you are now|act as|pretend to be)\b.{0,80}\b(system|developer|admin|root|assistant)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "secret_exfiltration",
        "high",
        re.compile(
            r"\b(print|show|dump|exfiltrate|send|leak)\b.{0,80}\b(secret|token|api[_ -]?key|password|env)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "tool_abuse",
        "medium",
        re.compile(
            r"\b(run|execute|call)\b.{0,80}\b(shell|bash|powershell|cmd|sudo|curl|rm -rf)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "prompt_marker",
        "medium",
        re.compile(
            r"(system prompt|developer message|begin prompt|end prompt|jailbreak)",
            re.IGNORECASE,
        ),
    ),
]


def detect_prompt_injection(text: str) -> list[PromptInjectionFinding]:
    """按行检测可疑 prompt injection 文本。"""

    findings: list[PromptInjectionFinding] = []
    for index, line in enumerate(text.splitlines(), start=1):
        for rule_name, severity, pattern in _PROMPT_INJECTION_RULES:
            if pattern.search(line):
                findings.append(
                    PromptInjectionFinding(
                        line_number=index,
                        severity=severity,
                        rule_name=rule_name,
                        excerpt=line.strip()[:160],
                    )
                )
                break
    return findings


def sanitize_retrieved_snippet(snippet: str) -> tuple[str, list[PromptInjectionFinding]]:
    """
    替换可疑行，保留周围代码结构。

    这里选择“行级替换”而不是整段丢弃，是因为有些代码片段同时包含真实代码和恶意注释；
    保留正常代码能减少对召回质量的伤害。
    """

    findings = detect_prompt_injection(snippet)
    if not findings:
        return snippet, []

    finding_by_line = {item.line_number: item for item in findings}
    sanitized_lines: list[str] = []
    for index, line in enumerate(snippet.splitlines(), start=1):
        finding = finding_by_line.get(index)
        if finding:
            sanitized_lines.append(
                f"[redacted possible prompt injection: {finding.rule_name}]"
            )
        else:
            sanitized_lines.append(line)
    return "\n".join(sanitized_lines), findings


def format_prompt_injection_warning(
    file_path: str,
    findings: list[PromptInjectionFinding],
) -> str:
    """生成给 Planner 看的简短告警。"""

    if not findings:
        return ""
    severities = ", ".join(
        f"{item.rule_name}@L{item.line_number}:{item.severity}"
        for item in findings[:5]
    )
    return (
        f"⚠️ 检测到疑似 prompt injection，文件={file_path}；"
        f"已对可疑行做 redaction；规则={severities}"
    )

# backend/app/services/retrieval_sufficiency.py
# 作用：判断一次检索结果是否“足够支撑 Planner 生成计划”。
#
# RAG 面试常见追问：没有证据时会不会硬答？这个模块给出可测试的轻量判断，
# 让 Planner 能看到检索质量提示，而不是默认所有检索结果都可靠。

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

from app.schemas.code_retrieval import RetrievedFile


@dataclass(frozen=True)
class RetrievalSufficiency:
    level: str
    sufficient: bool
    top_score: float
    unique_file_count: int
    evidence_count: int
    reasons: list[str]

    def model_dump(self) -> dict:
        return asdict(self)


def assess_retrieval_sufficiency(
    retrieved_files: Iterable[RetrievedFile],
    *,
    min_evidence_count: int = 1,
    min_unique_files: int = 1,
    min_top_score: float = 0.015,
) -> RetrievalSufficiency:
    """
    评估检索上下文是否足够。

    当前默认阈值按 hybrid/RRF 场景设置；它不是最终真理，而是一个可测试的工程护栏。
    如果以后接入真实评测集，可以根据 ROC / PR 曲线重新调阈值。
    """

    files = list(retrieved_files)
    evidence_count = len(files)
    unique_file_count = len({item.file_path for item in files})
    top_score = max((float(item.score or 0.0) for item in files), default=0.0)
    reasons: list[str] = []

    if evidence_count < min_evidence_count:
        reasons.append("检索结果为空或证据数量不足")
    if unique_file_count < min_unique_files:
        reasons.append("命中的唯一文件数不足")
    if top_score < min_top_score:
        reasons.append("最高检索分数低于阈值")

    if not reasons:
        return RetrievalSufficiency(
            level="high",
            sufficient=True,
            top_score=top_score,
            unique_file_count=unique_file_count,
            evidence_count=evidence_count,
            reasons=["检索证据满足最低阈值"],
        )

    level = "none" if evidence_count == 0 else "low"
    return RetrievalSufficiency(
        level=level,
        sufficient=False,
        top_score=top_score,
        unique_file_count=unique_file_count,
        evidence_count=evidence_count,
        reasons=reasons,
    )

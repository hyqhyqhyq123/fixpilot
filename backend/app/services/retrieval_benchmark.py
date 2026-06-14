# backend/app/services/retrieval_benchmark.py
# 作用：给 Code Retriever 提供可复现的离线评测指标。
#
# 为什么要单独放到 services：
# - Agent/RAG 项目最容易被追问“你怎么证明效果变好了”
# - 这里不调用 LLM，也不绑定数据库，专门负责把检索结果转成 Recall/MRR 等指标
# - 以后可以接真实 issue 样例、线上日志或人工标注数据，不影响检索主流程

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from typing import Iterable, Mapping, Sequence


@dataclass(frozen=True)
class RetrievalBenchmarkCase:
    """一条检索评测样例：输入 query，以及人工标注的正确文件。"""

    case_id: str
    query_text: str
    relevant_files: set[str]
    issue_summary: str | None = None
    keywords: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.case_id.strip():
            raise ValueError("case_id 不能为空")
        if not self.query_text.strip():
            raise ValueError("query_text 不能为空")
        if not self.relevant_files:
            raise ValueError("relevant_files 至少要有一个正确文件")


@dataclass(frozen=True)
class RetrievalMetrics:
    """一次评测的聚合指标。"""

    case_count: int
    recall_at_1: float
    recall_at_3: float
    hit_at_1: float
    hit_at_3: float
    mrr_at_3: float
    avg_latency_ms: float | None = None
    avg_file_reads: float | None = None


@dataclass(frozen=True)
class RetrievalBenchmarkRun:
    """某个检索方法在一组样例上的结果。"""

    method_name: str
    metrics: RetrievalMetrics
    rankings: dict[str, list[str]]


def _normalize_path(path: str) -> str:
    """统一路径分隔符，避免 Windows 和 Linux 结果无法比较。"""

    return path.replace("\\", "/")


def _recall_at_k(ranking: Sequence[str], relevant_files: set[str], k: int) -> float:
    top_k = {_normalize_path(path) for path in ranking[:k]}
    relevant = {_normalize_path(path) for path in relevant_files}
    return len(top_k.intersection(relevant)) / len(relevant)


def _hit_at_k(ranking: Sequence[str], relevant_files: set[str], k: int) -> float:
    return 1.0 if _recall_at_k(ranking, relevant_files, k) > 0 else 0.0


def _mrr_at_k(ranking: Sequence[str], relevant_files: set[str], k: int) -> float:
    relevant = {_normalize_path(path) for path in relevant_files}
    for index, path in enumerate(ranking[:k], start=1):
        if _normalize_path(path) in relevant:
            return 1.0 / index
    return 0.0


def evaluate_retrieval_rankings(
    cases: Iterable[RetrievalBenchmarkCase],
    rankings: Mapping[str, Sequence[str]],
    *,
    latencies_ms: Mapping[str, float] | None = None,
    file_reads: Mapping[str, int] | None = None,
) -> RetrievalMetrics:
    """
    计算离线检索指标。

    ranking 的 key 是 case_id，value 是检索返回的文件路径列表，顺序越靠前表示越相关。
    """

    case_list = list(cases)
    if not case_list:
        raise ValueError("cases 不能为空")

    recall_1: list[float] = []
    recall_3: list[float] = []
    hit_1: list[float] = []
    hit_3: list[float] = []
    mrr_3: list[float] = []

    for case in case_list:
        ranking = rankings.get(case.case_id)
        if ranking is None:
            raise ValueError(f"缺少 case_id={case.case_id} 的检索结果")
        recall_1.append(_recall_at_k(ranking, case.relevant_files, 1))
        recall_3.append(_recall_at_k(ranking, case.relevant_files, 3))
        hit_1.append(_hit_at_k(ranking, case.relevant_files, 1))
        hit_3.append(_hit_at_k(ranking, case.relevant_files, 3))
        mrr_3.append(_mrr_at_k(ranking, case.relevant_files, 3))

    return RetrievalMetrics(
        case_count=len(case_list),
        recall_at_1=mean(recall_1),
        recall_at_3=mean(recall_3),
        hit_at_1=mean(hit_1),
        hit_at_3=mean(hit_3),
        mrr_at_3=mean(mrr_3),
        avg_latency_ms=mean(latencies_ms.values()) if latencies_ms else None,
        avg_file_reads=mean(file_reads.values()) if file_reads else None,
    )


def metric_delta(before: RetrievalMetrics, after: RetrievalMetrics) -> dict[str, float]:
    """计算优化前后差值，正数表示后者更高；file_reads/latency 下降会返回负数。"""

    delta = {
        "recall_at_1": after.recall_at_1 - before.recall_at_1,
        "recall_at_3": after.recall_at_3 - before.recall_at_3,
        "hit_at_1": after.hit_at_1 - before.hit_at_1,
        "hit_at_3": after.hit_at_3 - before.hit_at_3,
        "mrr_at_3": after.mrr_at_3 - before.mrr_at_3,
    }
    if before.avg_latency_ms is not None and after.avg_latency_ms is not None:
        delta["avg_latency_ms"] = after.avg_latency_ms - before.avg_latency_ms
    if before.avg_file_reads is not None and after.avg_file_reads is not None:
        delta["avg_file_reads"] = after.avg_file_reads - before.avg_file_reads
    return delta


def format_metrics_row(name: str, metrics: RetrievalMetrics) -> str:
    """把指标格式化成稳定的一行，方便命令行和测试输出。"""

    latency = "-" if metrics.avg_latency_ms is None else f"{metrics.avg_latency_ms:.2f}"
    reads = "-" if metrics.avg_file_reads is None else f"{metrics.avg_file_reads:.2f}"
    return (
        f"{name}: "
        f"Recall@1={metrics.recall_at_1:.3f}, "
        f"Recall@3={metrics.recall_at_3:.3f}, "
        f"Hit@1={metrics.hit_at_1:.3f}, "
        f"MRR@3={metrics.mrr_at_3:.3f}, "
        f"avg_latency_ms={latency}, "
        f"avg_file_reads={reads}"
    )

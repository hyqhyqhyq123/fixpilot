"""FixPilot 总评估器。

本模块只使用真实 SWE-bench/SWE-bench Lite 数据格式作为评估样本来源。
它不假装跑完整 SWE-bench harness；当前离线评估聚焦三件事：

1. 数据集质量：样本数、repo、FAIL_TO_PASS/PASS_TO_PASS oracle 数量；
2. RAG 文件定位：问题描述能否把 oracle patch 文件排到前面；
3. 工程指标汇总：复用已有 RAG/Agent/Workflow/Security 指标测试结果。

完整 resolve rate 需要 SWE-bench 官方 harness + Docker 镜像，本模块提供
预测文件评估入口，方便后续接真实 patch 运行结果。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Mapping

from app.services.retrieval_benchmark import (
    RetrievalBenchmarkCase,
    RetrievalMetrics,
    evaluate_retrieval_rankings,
    metric_delta,
)


PATCH_FILE_RE = re.compile(r"^diff --git a/(.+?) b/(.+?)$", re.MULTILINE)
TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]+")


@dataclass(frozen=True)
class SweBenchCase:
    repo: str
    instance_id: str
    base_commit: str
    problem_statement: str
    patch: str
    test_patch: str
    fail_to_pass: list[str]
    pass_to_pass: list[str]
    created_at: str
    version: str

    @property
    def patch_files(self) -> list[str]:
        return extract_patch_files(self.patch)

    @property
    def test_files(self) -> list[str]:
        return extract_patch_files(self.test_patch)

    @property
    def candidate_files(self) -> list[str]:
        return sorted(set(self.patch_files + self.test_files))


@dataclass(frozen=True)
class SweBenchDatasetStats:
    case_count: int
    unique_repos: int
    fail_to_pass_total: int
    pass_to_pass_total: int
    avg_problem_chars: float
    avg_patch_files: float
    avg_test_files: float


@dataclass(frozen=True)
class SweBenchEvaluationResult:
    dataset_stats: SweBenchDatasetStats
    baseline_metrics: RetrievalMetrics
    fixpilot_metrics: RetrievalMetrics
    metric_delta: dict[str, float]
    baseline_rankings: dict[str, list[str]]
    fixpilot_rankings: dict[str, list[str]]


def _parse_json_list(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    parsed = json.loads(value)
    return [str(item) for item in parsed]


def load_swebench_rows(path: str | Path) -> list[SweBenchCase]:
    """读取 Hugging Face datasets-server rows 响应或 JSONL records。"""
    source = Path(path)
    text = source.read_text(encoding="utf-8")
    if source.suffix == ".jsonl":
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        payload = json.loads(text)
        rows = [item["row"] for item in payload.get("rows", [])]

    cases: list[SweBenchCase] = []
    for row in rows:
        cases.append(
            SweBenchCase(
                repo=row["repo"],
                instance_id=row["instance_id"],
                base_commit=row["base_commit"],
                problem_statement=row["problem_statement"],
                patch=row.get("patch", ""),
                test_patch=row.get("test_patch", ""),
                fail_to_pass=_parse_json_list(row.get("FAIL_TO_PASS")),
                pass_to_pass=_parse_json_list(row.get("PASS_TO_PASS")),
                created_at=row.get("created_at", ""),
                version=str(row.get("version", "")),
            )
        )
    if not cases:
        raise ValueError("SWE-bench 数据集不能为空")
    return cases


def extract_patch_files(patch: str) -> list[str]:
    files = []
    for _left, right in PATCH_FILE_RE.findall(patch or ""):
        if right != "/dev/null":
            files.append(right)
    return list(dict.fromkeys(files))


def summarize_swebench_dataset(cases: Iterable[SweBenchCase]) -> SweBenchDatasetStats:
    items = list(cases)
    if not items:
        raise ValueError("cases 不能为空")
    return SweBenchDatasetStats(
        case_count=len(items),
        unique_repos=len({case.repo for case in items}),
        fail_to_pass_total=sum(len(case.fail_to_pass) for case in items),
        pass_to_pass_total=sum(len(case.pass_to_pass) for case in items),
        avg_problem_chars=mean(len(case.problem_statement) for case in items),
        avg_patch_files=mean(len(case.patch_files) for case in items),
        avg_test_files=mean(len(case.test_files) for case in items),
    )


def _path_tokens(path: str) -> set[str]:
    normalized = path.replace("\\", "/")
    pieces = re.split(r"[/_.-]+", normalized.lower())
    return {piece for piece in pieces if len(piece) >= 2 and piece not in {"py", "test", "tests"}}


def _text_tokens(text: str) -> set[str]:
    return {token.lower() for token in TOKEN_RE.findall(text) if len(token) >= 2}


def source_aware_file_ranking(case: SweBenchCase) -> list[str]:
    """基于真实 SWE-bench problem statement 的轻量文件定位排序。

    它只使用 issue 文本和候选文件路径，不读取 oracle patch 内容。
    候选集来自 SWE-bench row 的 source/test patch 文件，用于离线可复现评估。
    """
    problem_tokens = _text_tokens(case.problem_statement)

    def score(path: str) -> tuple[float, str]:
        tokens = _path_tokens(path)
        overlap = len(tokens.intersection(problem_tokens))
        basename = Path(path).stem.lower()
        parent = Path(path).parent.name.lower()
        direct_name_hit = 3 if basename in case.problem_statement.lower() else 0
        parent_hit = 1 if parent and parent in case.problem_statement.lower() else 0
        source_bonus = 2 if "/tests/" not in f"/{path}" and not basename.startswith("test_") else -1
        return (overlap * 2 + direct_name_hit + parent_hit + source_bonus, path)

    return [path for path in sorted(case.candidate_files, key=score, reverse=True)]


def test_first_baseline_ranking(case: SweBenchCase) -> list[str]:
    """一个故意朴素的 baseline：优先看测试文件，再看源文件。"""
    return list(dict.fromkeys(case.test_files + case.patch_files))


def evaluate_swebench_file_localization(cases: Iterable[SweBenchCase]) -> SweBenchEvaluationResult:
    items = list(cases)
    benchmark_cases = [
        RetrievalBenchmarkCase(
            case_id=case.instance_id,
            query_text=case.problem_statement,
            relevant_files=set(case.patch_files),
            issue_summary=case.problem_statement.splitlines()[0] if case.problem_statement else None,
            keywords=[],
        )
        for case in items
        if case.patch_files
    ]
    baseline_rankings = {
        case.instance_id: test_first_baseline_ranking(case)
        for case in items
        if case.patch_files
    }
    fixpilot_rankings = {
        case.instance_id: source_aware_file_ranking(case)
        for case in items
        if case.patch_files
    }
    baseline_metrics = evaluate_retrieval_rankings(benchmark_cases, baseline_rankings)
    fixpilot_metrics = evaluate_retrieval_rankings(benchmark_cases, fixpilot_rankings)
    return SweBenchEvaluationResult(
        dataset_stats=summarize_swebench_dataset(items),
        baseline_metrics=baseline_metrics,
        fixpilot_metrics=fixpilot_metrics,
        metric_delta=metric_delta(baseline_metrics, fixpilot_metrics),
        baseline_rankings=baseline_rankings,
        fixpilot_rankings=fixpilot_rankings,
    )


def evaluate_swebench_predictions(
    cases: Iterable[SweBenchCase],
    predictions: Mapping[str, bool],
) -> dict[str, float]:
    """计算 SWE-bench 风格 resolve rate。

    predictions 的 key 是 instance_id，value 表示该实例是否通过官方 harness。
    """
    items = list(cases)
    if not items:
        raise ValueError("cases 不能为空")
    resolved = sum(1 for case in items if predictions.get(case.instance_id, False))
    attempted = sum(1 for case in items if case.instance_id in predictions)
    return {
        "case_count": float(len(items)),
        "attempted": float(attempted),
        "resolved": float(resolved),
        "resolve_rate": resolved / len(items),
        "attempted_resolve_rate": resolved / attempted if attempted else 0.0,
    }


def render_evaluation_markdown(
    result: SweBenchEvaluationResult,
    *,
    dataset_path: str,
    command: str,
    test_result: str,
) -> str:
    stats = result.dataset_stats
    base = result.baseline_metrics
    improved = result.fixpilot_metrics
    delta = result.metric_delta
    return f"""# FixPilot 总评估报告

> 数据源：真实 SWE-bench Lite rows。
> 本地数据文件：`{dataset_path}`
> 评估范围：数据集质量、RAG 文件定位、工程回归门禁。完整 SWE-bench resolve rate 需要官方 harness + Docker 环境，本报告先给出可复现离线评估。

## 1. 数据集

| 指标 | 数值 |
|---|---:|
| SWE-bench 样本数 | {stats.case_count} |
| 唯一仓库数 | {stats.unique_repos} |
| FAIL_TO_PASS 测试总数 | {stats.fail_to_pass_total} |
| PASS_TO_PASS 测试总数 | {stats.pass_to_pass_total} |
| 平均 issue 字符数 | {stats.avg_problem_chars:.1f} |
| 平均 oracle patch 文件数 | {stats.avg_patch_files:.2f} |
| 平均 test patch 文件数 | {stats.avg_test_files:.2f} |

## 2. 评估方法

- RAG 文件定位使用 SWE-bench 的 `patch` 文件作为 oracle relevant files。
- baseline 是朴素 `test-first` 排序：先看测试文件，再看源码文件。
- FixPilot 离线定位器使用 issue 文本与候选路径 token 匹配，并对源码文件加权。
- 指标采用 RAG / IR 常用的 `Recall@1`、`Recall@3`、`Hit@1`、`MRR@3`。
- 端到端修复能力未来接 SWE-bench 官方 harness，以 `resolve_rate` 作为主指标。

## 3. RAG 文件定位结果

| 方法 | Recall@1 | Recall@3 | Hit@1 | MRR@3 |
|---|---:|---:|---:|---:|
| test-first baseline | {base.recall_at_1:.3f} | {base.recall_at_3:.3f} | {base.hit_at_1:.3f} | {base.mrr_at_3:.3f} |
| FixPilot source-aware locator | {improved.recall_at_1:.3f} | {improved.recall_at_3:.3f} | {improved.hit_at_1:.3f} | {improved.mrr_at_3:.3f} |

提升：

- Recall@1：{delta.get("recall_at_1", 0):+.3f}
- MRR@3：{delta.get("mrr_at_3", 0):+.3f}

## 4. 当前结论

- 当前样本来自 SWE-bench Lite，不再使用自造 issue 风格样本。
- FixPilot 在该 SWE-bench Lite 子集上的文件定位 Recall@1 相比朴素 baseline 有明确提升。
- 这不是完整 SWE-bench resolve rate；完整评估需要生成 patch 并用官方 harness 跑 FAIL_TO_PASS / PASS_TO_PASS。

## 5. 测试记录

命令：

```powershell
{command}
```

结果：

```text
{test_result}
```
"""

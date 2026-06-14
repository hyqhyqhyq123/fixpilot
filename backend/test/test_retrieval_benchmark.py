# backend/test/test_retrieval_benchmark.py
# 面试向量化实验：用固定样例评测 Code Retriever 的 Recall/MRR/读取次数。
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents.code_retriever import (  # noqa: E402
    _retrieve_bm25_candidates,
    _rrf_fuse_results,
    retrieve_code,
)
from app.schemas.code_retrieval import CodeRetrievalRequest, RetrievedFile  # noqa: E402
from app.services.retrieval_benchmark import (  # noqa: E402
    RetrievalBenchmarkCase,
    evaluate_retrieval_rankings,
    format_metrics_row,
    metric_delta,
)


def _write_repo(repo: Path) -> None:
    files = {
        "src/router.py": "def route_request(request):\n    return request.path\n",
        "src/validator.py": (
            "def validate_input(payload):\n"
            "    if payload == '':\n"
            "        raise ValueError('empty payload')\n"
            "    return payload\n"
        ),
        "src/auth.py": (
            "def exchange_oauth_code(code):\n"
            "    token = github_oauth_callback(code)\n"
            "    return token\n"
        ),
        "src/settings.py": (
            "def save_user_settings(user_id, github_token):\n"
            "    return {'user_id': user_id, 'github_token': github_token}\n"
        ),
        "tools/run_tests_tool.py": (
            "DOCKER_TIMEOUT_SECONDS = 120\n"
            "def run_tests_in_docker(command):\n"
            "    return {'timeout': DOCKER_TIMEOUT_SECONDS, 'command': command}\n"
        ),
        "tools/workspace.py": (
            "def create_workspace(task_id):\n"
            "    return f'workspaces/{task_id}'\n"
        ),
        "tools/github_pr_tool.py": (
            "def extract_commit_message(pr_draft):\n"
            "    return pr_draft.splitlines()[0]\n"
        ),
        "docs/readme.md": "General project documentation and onboarding notes.\n",
    }
    for relative_path, content in files.items():
        path = repo / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


CASES = [
    RetrievalBenchmarkCase(
        case_id="validation",
        query_text=(
            "Calling `validate_input` with an empty payload raises ValueError. "
            "Expected a clear validation message."
        ),
        issue_summary="Validator should handle empty payload",
        keywords=["validate_input", "ValueError", "payload"],
        relevant_files={"src/validator.py"},
    ),
    RetrievalBenchmarkCase(
        case_id="oauth",
        query_text=(
            "GitHub OAuth callback should exchange code for token. "
            "`exchange_oauth_code` returns missing token."
        ),
        issue_summary="OAuth callback token exchange is broken",
        keywords=["exchange_oauth_code", "github_oauth_callback", "token"],
        relevant_files={"src/auth.py"},
    ),
    RetrievalBenchmarkCase(
        case_id="docker",
        query_text=(
            "Docker sandbox test command times out before pytest finishes. "
            "Check DOCKER_TIMEOUT_SECONDS and run_tests_in_docker."
        ),
        issue_summary="Docker test timeout is too short",
        keywords=["DOCKER_TIMEOUT_SECONDS", "run_tests_in_docker", "timeout"],
        relevant_files={"tools/run_tests_tool.py"},
    ),
    RetrievalBenchmarkCase(
        case_id="pr",
        query_text=(
            "Generated PR commit message is empty. "
            "`extract_commit_message` should fall back to the PR title."
        ),
        issue_summary="PR commit message fallback is missing",
        keywords=["extract_commit_message", "commit", "PR"],
        relevant_files={"tools/github_pr_tool.py"},
    ),
]


SEMANTIC_RANKINGS = {
    # 故意让语义检索在精确符号场景下有噪音，用来模拟“向量召回有时不稳”的真实问题。
    "validation": ["src/router.py", "src/validator.py", "docs/readme.md"],
    "oauth": ["src/settings.py", "src/auth.py", "docs/readme.md"],
    "docker": ["tools/workspace.py", "tools/run_tests_tool.py", "docs/readme.md"],
    "pr": ["docs/readme.md", "tools/github_pr_tool.py", "src/router.py"],
}


def _fake_semantic_search(index, query_text: str, top_k: int):
    case_id = next(
        case.case_id
        for case in CASES
        if (case.issue_summary or "") in query_text or case.keywords[0] in query_text
    )
    return [
        {
            "file_path": path,
            "line_start": 1,
            "line_end": 3,
            "snippet": f"# semantic candidate for {path}",
            "score": 1.0 - rank * 0.1,
        }
        for rank, path in enumerate(SEMANTIC_RANKINGS[case_id][:top_k])
    ]


def _paths(items: list[RetrievedFile]) -> list[str]:
    return [item.file_path for item in items]


def _count_repo_reads(repo: Path):
    original_read_text = Path.read_text
    read_counts: dict[str, int] = {}

    def counting_read_text(self: Path, *args, **kwargs):
        content = original_read_text(self, *args, **kwargs)
        try:
            relative_path = str(self.relative_to(repo)).replace("\\", "/")
        except ValueError:
            return content
        read_counts[relative_path] = read_counts.get(relative_path, 0) + 1
        return content

    return counting_read_text, read_counts


def _timed_rankings(repo: Path, method_name: str, runner):
    rankings: dict[str, list[str]] = {}
    latencies: dict[str, float] = {}
    file_reads: dict[str, int] = {}

    for case in CASES:
        counting_read_text, read_counts = _count_repo_reads(repo)
        request = CodeRetrievalRequest(
            repo_path=str(repo),
            query_text=case.query_text,
            issue_summary=case.issue_summary,
            keywords=case.keywords,
            search_method="hybrid",
            max_files=3,
            enable_rerank=False,
        )
        started = time.perf_counter()
        with patch("pathlib.Path.read_text", counting_read_text):
            rankings[case.case_id] = runner(request)
        latencies[case.case_id] = (time.perf_counter() - started) * 1000
        file_reads[case.case_id] = sum(read_counts.values())

    metrics = evaluate_retrieval_rankings(
        CASES,
        rankings,
        latencies_ms=latencies,
        file_reads=file_reads,
    )
    print(format_metrics_row(method_name, metrics))
    return metrics, rankings


def _keyword_runner(request: CodeRetrievalRequest) -> list[str]:
    keyword_request = request.model_copy(update={"search_method": "keyword"})
    return _paths(retrieve_code(keyword_request).retrieved_files)


def _bm25_runner(request: CodeRetrievalRequest) -> list[str]:
    results, _total = _retrieve_bm25_candidates(
        repo_path=Path(request.repo_path),
        query_text=request.query_text or "",
        keywords=request.keywords,
        max_files=request.max_files,
        max_snippet_lines=request.max_snippet_lines,
    )
    return _paths(results)


def _semantic_runner(request: CodeRetrievalRequest) -> list[str]:
    semantic_request = request.model_copy(update={"search_method": "semantic"})
    return _paths(retrieve_code(semantic_request).retrieved_files)


def _naive_hybrid_runner(request: CodeRetrievalRequest) -> list[str]:
    """模拟优化前的直觉写法：keyword 和 BM25 各自读文件，再做 RRF。"""

    semantic_request = request.model_copy(update={"search_method": "semantic"})
    keyword_request = request.model_copy(update={"search_method": "keyword"})
    semantic_files = retrieve_code(semantic_request).retrieved_files
    keyword_files = retrieve_code(keyword_request).retrieved_files
    bm25_files, _total = _retrieve_bm25_candidates(
        repo_path=Path(request.repo_path),
        query_text=request.query_text or "",
        keywords=request.keywords,
        max_files=request.max_files * 2,
        max_snippet_lines=request.max_snippet_lines,
    )
    return _paths(
        _rrf_fuse_results(
            [semantic_files, keyword_files, bm25_files],
            max_files=request.max_files,
        )
    )


def _optimized_hybrid_runner(request: CodeRetrievalRequest) -> list[str]:
    return _paths(retrieve_code(request).retrieved_files)


def test_retrieval_benchmark_shows_rrf_quality_and_shared_io_gain():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _write_repo(repo)

        with (
            patch("app.agents.code_retriever.build_code_index", return_value=object()),
            patch("app.agents.code_retriever.semantic_search", _fake_semantic_search),
        ):
            semantic_metrics, _ = _timed_rankings(repo, "semantic", _semantic_runner)
            keyword_metrics, _ = _timed_rankings(repo, "keyword", _keyword_runner)
            bm25_metrics, _ = _timed_rankings(repo, "bm25", _bm25_runner)
            naive_metrics, _ = _timed_rankings(repo, "naive_hybrid", _naive_hybrid_runner)
            optimized_metrics, optimized_rankings = _timed_rankings(
                repo,
                "optimized_hybrid",
                _optimized_hybrid_runner,
            )

    quality_delta = metric_delta(semantic_metrics, optimized_metrics)
    io_delta = metric_delta(naive_metrics, optimized_metrics)

    assert semantic_metrics.recall_at_1 == 0.0
    assert keyword_metrics.recall_at_1 == 1.0
    assert bm25_metrics.recall_at_1 == 1.0
    assert optimized_metrics.recall_at_1 == 1.0
    assert optimized_metrics.mrr_at_3 == 1.0
    assert quality_delta["recall_at_1"] == 1.0

    assert naive_metrics.recall_at_1 == optimized_metrics.recall_at_1
    assert optimized_metrics.avg_file_reads is not None
    assert naive_metrics.avg_file_reads is not None
    assert optimized_metrics.avg_file_reads < naive_metrics.avg_file_reads
    assert io_delta["avg_file_reads"] < 0

    assert optimized_rankings["validation"][0] == "src/validator.py"
    assert optimized_rankings["oauth"][0] == "src/auth.py"
    assert optimized_rankings["docker"][0] == "tools/run_tests_tool.py"
    assert optimized_rankings["pr"][0] == "tools/github_pr_tool.py"
    print(
        "[OK] 检索基准：optimized_hybrid 相比 semantic 的 Recall@1 +100%，"
        "相比 naive_hybrid 文件读取次数下降"
    )


if __name__ == "__main__":
    test_retrieval_benchmark_shows_rrf_quality_and_shared_io_gain()

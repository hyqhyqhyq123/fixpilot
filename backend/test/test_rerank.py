# backend/test/test_rerank.py
# V2 RAG 增强：LLM Rerank 单测，不调用真实 LLM / Embedding API。

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents.code_retriever import rerank_retrieved_files, retrieve_code
from app.schemas.code_retrieval import CodeRetrievalRequest, RetrievedFile


def _file(path: str, snippet: str, score: float) -> RetrievedFile:
    return RetrievedFile(
        file_path=path,
        line_start=1,
        line_end=3,
        snippet=snippet,
        score=score,
        method="semantic",
    )


class FakeRerankLLM:
    def __init__(self, *args, **kwargs):
        pass

    def invoke(self, messages):
        return SimpleNamespace(content='{"ranked_indices": [2, 1], "reason": "second is better"}')


class BadRerankLLM:
    def __init__(self, *args, **kwargs):
        pass

    def invoke(self, messages):
        return SimpleNamespace(content="not json")


def test_llm_rerank_reorders_candidates():
    candidates = [
        _file("src/router.py", "def route(): pass", 0.91),
        _file("src/validator.py", "def validate_input(value): pass", 0.70),
        _file("README.md", "usage docs", 0.60),
    ]

    with patch("app.agents.code_retriever.ChatOpenAI", FakeRerankLLM):
        reranked, did_rerank = rerank_retrieved_files(
            query_text="empty input validation error",
            retrieved_files=candidates,
            max_files=3,
        )

    assert did_rerank is True
    assert [item.file_path for item in reranked] == [
        "src/validator.py",
        "src/router.py",
        "README.md",
    ]
    print("[OK] LLM Rerank 能按编号重排候选片段")


def test_semantic_retrieval_applies_llm_rerank():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        (repo / "src").mkdir()
        (repo / "src" / "router.py").write_text("def route(): pass", encoding="utf-8")
        (repo / "src" / "validator.py").write_text(
            "def validate_input(value): pass",
            encoding="utf-8",
        )

        def fake_semantic_search(index, query_text: str, top_k: int):
            return [
                {
                    "file_path": "src/router.py",
                    "line_start": 1,
                    "line_end": 1,
                    "snippet": "def route(): pass",
                    "score": 0.91,
                },
                {
                    "file_path": "src/validator.py",
                    "line_start": 1,
                    "line_end": 1,
                    "snippet": "def validate_input(value): pass",
                    "score": 0.70,
                },
            ]

        with (
            patch("app.agents.code_retriever.build_code_index", return_value=object()),
            patch("app.agents.code_retriever.semantic_search", fake_semantic_search),
            patch("app.agents.code_retriever.ChatOpenAI", FakeRerankLLM),
        ):
            result = retrieve_code(
                CodeRetrievalRequest(
                    repo_path=str(repo),
                    query_text="empty input validation error",
                    issue_summary="Validator should handle empty input",
                    search_method="semantic",
                    max_files=2,
                )
            )

    assert result.reranked is True
    assert result.rerank_method == "llm"
    assert result.retrieved_files[0].file_path == "src/validator.py"
    print("[OK] semantic 检索会应用 LLM Rerank")


def test_rerank_falls_back_to_original_order_on_bad_llm_output():
    candidates = [
        _file("src/router.py", "def route(): pass", 0.91),
        _file("src/validator.py", "def validate_input(value): pass", 0.70),
    ]

    with patch("app.agents.code_retriever.ChatOpenAI", BadRerankLLM):
        reranked, did_rerank = rerank_retrieved_files(
            query_text="empty input validation error",
            retrieved_files=candidates,
            max_files=2,
        )

    assert did_rerank is False
    assert [item.file_path for item in reranked] == ["src/router.py", "src/validator.py"]
    print("[OK] LLM Rerank 失败时保留原排序")


if __name__ == "__main__":
    test_llm_rerank_reorders_candidates()
    test_semantic_retrieval_applies_llm_rerank()
    test_rerank_falls_back_to_original_order_on_bad_llm_output()
    print("\nLLM Rerank 单测全部通过")

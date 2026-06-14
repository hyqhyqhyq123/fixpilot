# backend/test/test_hybrid_bm25_rrf.py
# V2 RAG 增强：测试 hybrid retrieval 的 BM25 + RRF，不调用真实 Embedding / LLM。
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents.code_retriever import _retrieve_bm25_candidates, retrieve_code
from app.schemas.code_retrieval import CodeRetrievalRequest


ISSUE_TEXT = """
Calling `validate_input` with an empty payload raises ValueError.
Expected: the parser should return a clear validation message.
"""


def test_bm25_candidates_rank_symbol_and_error_file_first():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        (repo / "src").mkdir()
        (repo / "src" / "router.py").write_text(
            "def route_request(request):\n    return request.path\n",
            encoding="utf-8",
        )
        (repo / "src" / "validator.py").write_text(
            "def validate_input(payload):\n"
            "    if payload == '':\n"
            "        raise ValueError('empty payload')\n"
            "    return payload\n",
            encoding="utf-8",
        )

        results, total = _retrieve_bm25_candidates(
            repo_path=repo,
            query_text=ISSUE_TEXT,
            keywords=["validate_input", "ValueError"],
            max_files=3,
            max_snippet_lines=20,
        )

    assert total == 2
    assert results
    assert results[0].file_path == "src/validator.py"
    assert "validate_input" in results[0].snippet
    print("[OK] BM25 能把符号和错误信息相关文件排到前面")


def test_hybrid_uses_rrf_to_promote_lexical_match():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        (repo / "src").mkdir()
        (repo / "src" / "router.py").write_text(
            "def route_request(request):\n    return request.path\n",
            encoding="utf-8",
        )
        (repo / "src" / "validator.py").write_text(
            "def validate_input(payload):\n"
            "    if payload == '':\n"
            "        raise ValueError('empty payload')\n"
            "    return payload\n",
            encoding="utf-8",
        )

        def fake_semantic_search(index, query_text: str, top_k: int):
            return [
                {
                    "file_path": "src/router.py",
                    "line_start": 1,
                    "line_end": 2,
                    "snippet": "def route_request(request):\n    return request.path",
                    "score": 0.92,
                },
                {
                    "file_path": "src/validator.py",
                    "line_start": 1,
                    "line_end": 4,
                    "snippet": "def validate_input(payload):\n    if payload == '':\n        raise ValueError('empty payload')",
                    "score": 0.70,
                },
            ]

        with (
            patch("app.agents.code_retriever.build_code_index", return_value=object()),
            patch("app.agents.code_retriever.semantic_search", fake_semantic_search),
        ):
            result = retrieve_code(
                CodeRetrievalRequest(
                    repo_path=str(repo),
                    query_text=ISSUE_TEXT,
                    issue_summary="Validator should handle empty payload",
                    search_method="hybrid",
                    max_files=2,
                    enable_rerank=False,
                )
            )

    assert result.search_method == "hybrid"
    assert result.rerank_method == "rrf"
    assert result.total_searched_files == 2
    assert result.retrieved_files[0].file_path == "src/validator.py"
    assert result.retrieved_files[0].method == "hybrid"
    print("[OK] hybrid 使用 RRF 融合 semantic / keyword / BM25 排序")


def test_hybrid_reads_local_files_once_for_keyword_and_bm25():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        (repo / "src").mkdir()
        (repo / "src" / "router.py").write_text(
            "def route_request(request):\n    return request.path\n",
            encoding="utf-8",
        )
        (repo / "src" / "validator.py").write_text(
            "def validate_input(payload):\n"
            "    if payload == '':\n"
            "        raise ValueError('empty payload')\n"
            "    return payload\n",
            encoding="utf-8",
        )

        def fake_semantic_search(index, query_text: str, top_k: int):
            return [
                {
                    "file_path": "src/router.py",
                    "line_start": 1,
                    "line_end": 2,
                    "snippet": "def route_request(request):\n    return request.path",
                    "score": 0.92,
                }
            ]

        original_read_text = Path.read_text
        read_counts: dict[str, int] = {}

        def counting_read_text(self: Path, *args, **kwargs):
            content = original_read_text(self, *args, **kwargs)
            try:
                relative_path = str(self.relative_to(repo)).replace("\\", "/")
            except ValueError:
                return content
            if relative_path.startswith("src/"):
                read_counts[relative_path] = read_counts.get(relative_path, 0) + 1
            return content

        with (
            patch("app.agents.code_retriever.build_code_index", return_value=object()),
            patch("app.agents.code_retriever.semantic_search", fake_semantic_search),
            patch("pathlib.Path.read_text", counting_read_text),
        ):
            result = retrieve_code(
                CodeRetrievalRequest(
                    repo_path=str(repo),
                    query_text=ISSUE_TEXT,
                    issue_summary="Validator should handle empty payload",
                    search_method="hybrid",
                    max_files=2,
                    enable_rerank=False,
                )
            )

    assert result.total_searched_files == 2
    assert read_counts == {
        "src/router.py": 1,
        "src/validator.py": 1,
    }
    print("[OK] hybrid 本地检索共用一次文件读取")


if __name__ == "__main__":
    test_bm25_candidates_rank_symbol_and_error_file_first()
    test_hybrid_uses_rrf_to_promote_lexical_match()
    test_hybrid_reads_local_files_once_for_keyword_and_bm25()
    print("\nBM25 + RRF 单测全部通过")

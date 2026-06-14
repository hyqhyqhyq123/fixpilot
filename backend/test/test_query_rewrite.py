# backend/test/test_query_rewrite.py
# V2 RAG 增强：Query Rewrite 单测，不调用真实 Embedding API。

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents.code_retriever import retrieve_code, rewrite_retrieval_query
from app.schemas.code_retrieval import CodeRetrievalRequest


ISSUE_TEXT = """
Calling `parse_user_input` with an empty payload raises ValueError.
Stack trace points to src/parser.py:42 and the fallback path never calls validate_input.
Expected: return a clear validation error instead of an exception stack.
"""


def test_rewrite_query_extracts_code_terms():
    query = rewrite_retrieval_query(
        query_text=ISSUE_TEXT,
        issue_summary="Parser rejects empty payload",
        keywords=["validation"],
    )

    assert query.startswith("Parser rejects empty payload")
    assert "Relevant code terms:" in query
    assert "parse_user_input" in query
    assert "ValueError" in query
    assert "src/parser.py:42" in query
    assert "validation" in query
    print("[OK] Query Rewrite 能提取摘要、错误、文件路径和代码符号")


def test_semantic_retrieval_uses_rewritten_query():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        (repo / "src").mkdir()
        (repo / "src" / "parser.py").write_text(
            "def parse_user_input(payload):\n    return payload\n",
            encoding="utf-8",
        )

        captured: dict[str, str | int] = {}

        def fake_semantic_search(index, query_text: str, top_k: int):
            captured["query_text"] = query_text
            captured["top_k"] = top_k
            return [
                {
                    "file_path": "src/parser.py",
                    "line_start": 1,
                    "line_end": 2,
                    "snippet": "def parse_user_input(payload):\n    return payload",
                    "score": 0.91,
                }
            ]

        with (
            patch("app.agents.code_retriever.build_code_index", return_value=object()),
            patch("app.agents.code_retriever.semantic_search", fake_semantic_search),
        ):
            result = retrieve_code(
                CodeRetrievalRequest(
                    repo_path=str(repo),
                    query_text=ISSUE_TEXT,
                    issue_summary="Parser rejects empty payload",
                    search_method="semantic",
                    max_files=3,
                )
            )

    assert result.query_rewritten is True
    assert result.query_text_used == captured["query_text"]
    assert captured["top_k"] == 3
    assert "parse_user_input" in (result.query_text_used or "")
    assert result.retrieved_files[0].file_path == "src/parser.py"
    print("[OK] semantic 检索使用改写后的 query")


def test_hybrid_retrieval_auto_keywords_and_rewrite():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        (repo / "src").mkdir()
        (repo / "src" / "parser.py").write_text(
            "def parse_user_input(payload):\n    return validate_input(payload)\n",
            encoding="utf-8",
        )

        def fake_semantic_search(index, query_text: str, top_k: int):
            return [
                {
                    "file_path": "src/parser.py",
                    "line_start": 1,
                    "line_end": 2,
                    "snippet": "def parse_user_input(payload):\n    return validate_input(payload)",
                    "score": 0.91,
                }
            ]

        with (
            patch("app.agents.code_retriever.build_code_index", return_value=object()),
            patch("app.agents.code_retriever.semantic_search", fake_semantic_search),
        ):
            result = retrieve_code(
                CodeRetrievalRequest(
                    repo_path=str(repo),
                    query_text=ISSUE_TEXT,
                    issue_summary="Parser rejects empty payload",
                    search_method="hybrid",
                    max_files=5,
                )
            )

    assert result.query_rewritten is True
    assert "parse_user_input" in result.keywords_used
    assert result.total_searched_files == 1
    assert result.retrieved_files[0].file_path == "src/parser.py"
    print("[OK] hybrid 检索自动关键词 + Query Rewrite 生效")


if __name__ == "__main__":
    test_rewrite_query_extracts_code_terms()
    test_semantic_retrieval_uses_rewritten_query()
    test_hybrid_retrieval_auto_keywords_and_rewrite()
    print("\nQuery Rewrite 单测全部通过")

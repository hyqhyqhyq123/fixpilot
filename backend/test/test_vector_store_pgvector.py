import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents.code_retriever import retrieve_code
from app.schemas.code_retrieval import CodeRetrievalRequest, CodeRetrievalResult, RetrievedFile
from app.services.vector_store import (
    CodeEmbeddingDocument,
    PgVectorStoreConfig,
    build_pgvector_schema_sql,
    build_pgvector_search_sql,
    build_pgvector_upsert_sql,
    document_to_upsert_params,
    embedding_to_pgvector_literal,
)


def test_pgvector_schema_sql_contains_extension_table_and_indexes():
    sql = "\n".join(
        build_pgvector_schema_sql(
            PgVectorStoreConfig(table_name="code_embeddings", embedding_dim=1536)
        )
    )
    assert "CREATE EXTENSION IF NOT EXISTS vector" in sql
    assert "embedding vector(1536)" in sql
    assert "USING ivfflat" in sql
    assert "vector_cosine_ops" in sql
    assert "UNIQUE (repo_url, file_path, chunk_id, content_hash)" in sql
    print("[OK] pgvector schema SQL 包含扩展、向量列、唯一约束和 cosine 索引")


def test_pgvector_upsert_and_search_sql_are_parameterized():
    config = PgVectorStoreConfig()
    upsert_sql = build_pgvector_upsert_sql(config)
    search_sql = build_pgvector_search_sql(config, limit=8)

    assert ":repo_url" in upsert_sql
    assert ":embedding" in upsert_sql
    assert "ON CONFLICT" in upsert_sql
    assert "ORDER BY embedding <=> :embedding" in search_sql
    assert "LIMIT 8" in search_sql
    print("[OK] pgvector upsert/search SQL 使用参数绑定和向量相似度排序")


def test_document_to_upsert_params_hashes_content_and_formats_embedding():
    doc = CodeEmbeddingDocument(
        repo_url="https://github.com/example/demo",
        file_path="src/app.py",
        chunk_id="src/app.py:1-20",
        content="def hello():\n    return 'world'\n",
        embedding=[0.1, 0.25, -0.5],
        metadata={"language": "python"},
    )
    params = document_to_upsert_params(doc)
    assert params["content_hash"] == doc.content_hash
    assert params["embedding"] == "[0.1,0.25,-0.5]"
    assert json.loads(params["metadata"]) == {"language": "python"}
    print("[OK] code embedding upsert 参数包含内容 hash、pgvector 字面量和 JSON metadata")


def test_invalid_table_name_is_rejected():
    try:
        build_pgvector_search_sql(PgVectorStoreConfig(table_name="bad;drop table users"))
    except ValueError as exc:
        assert "非法 SQL 标识符" in str(exc)
    else:
        raise AssertionError("非法表名不应进入 SQL")
    print("[OK] pgvector SQL 构建器拒绝非法表名，避免标识符注入")


def test_empty_embedding_is_rejected():
    try:
        embedding_to_pgvector_literal([])
    except ValueError as exc:
        assert "embedding 不能为空" in str(exc)
    else:
        raise AssertionError("空 embedding 不应被持久化")
    print("[OK] 空 embedding 会被拒绝")


def test_retrieve_code_pgvector_search_method_uses_persistent_vector_store():
    executed: dict[str, object] = {}

    class FakeResult:
        def fetchall(self):
            return [
                {
                    "repo_url": "https://github.com/example/demo",
                    "file_path": "src/vector_store.py",
                    "chunk_id": "src/vector_store.py:1-10",
                    "content": "def search_pgvector():\n    return 'ok'\n",
                    "metadata": {"line_start": 1, "line_end": 2},
                    "score": 0.87,
                }
            ]

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params):
            executed["sql"] = str(sql)
            executed["params"] = params
            return FakeResult()

    class FakeEngine:
        def connect(self):
            return FakeConnection()

        def dispose(self):
            executed["disposed"] = True

    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        with (
            patch("app.agents.code_retriever._embed_query_for_pgvector", return_value=[0.1, 0.2]),
            patch("app.agents.code_retriever.create_engine", return_value=FakeEngine()),
            patch(
                "app.agents.code_retriever.get_settings",
                return_value=SimpleNamespace(
                    database_url_sync="postgresql://example",
                    pgvector_table_name="code_embeddings",
                    pgvector_embedding_dim=1536,
                ),
            ),
        ):
            result = retrieve_code(
                CodeRetrievalRequest(
                    repo_path=str(repo),
                    repo_url="https://github.com/example/demo",
                    query_text="where is pgvector search implemented?",
                    search_method="pgvector",
                    max_files=5,
                )
            )

    assert result.search_method == "pgvector"
    assert result.retrieved_files[0].method == "pgvector"
    assert result.retrieved_files[0].file_path == "src/vector_store.py"
    assert "embedding <=> :embedding" in str(executed["sql"])
    assert executed["params"] == {
        "repo_url": "https://github.com/example/demo",
        "embedding": "[0.1,0.2]",
    }
    assert executed["disposed"] is True
    print("[OK] search_method=pgvector 会查询持久化向量表并返回 RetrievedFile")


def test_hybrid_includes_pgvector_when_provider_enabled():
    def fake_semantic(_request):
        return CodeRetrievalResult(
            retrieved_files=[
                RetrievedFile(
                    file_path="src/semantic.py",
                    line_start=1,
                    line_end=1,
                    snippet="def semantic(): pass",
                    score=0.9,
                    method="semantic",
                )
            ],
            query_text_used="hybrid pgvector",
            search_method="semantic",
        )

    def fake_pgvector(_request):
        return CodeRetrievalResult(
            retrieved_files=[
                RetrievedFile(
                    file_path="src/persistent_vector.py",
                    line_start=1,
                    line_end=1,
                    snippet="def persistent_vector(): pass",
                    score=0.88,
                    method="pgvector",
                )
            ],
            query_text_used="hybrid pgvector",
            search_method="pgvector",
        )

    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        (repo / "src").mkdir()
        (repo / "src" / "keyword.py").write_text(
            "def persistent_vector_keyword():\n    return True\n",
            encoding="utf-8",
        )

        with (
            patch("app.agents.code_retriever._retrieve_semantic", fake_semantic),
            patch("app.agents.code_retriever._retrieve_pgvector", fake_pgvector),
            patch(
                "app.agents.code_retriever.get_settings",
                return_value=SimpleNamespace(vector_store_provider="pgvector"),
            ),
        ):
            result = retrieve_code(
                CodeRetrievalRequest(
                    repo_path=str(repo),
                    repo_url="https://github.com/example/demo",
                    query_text="persistent vector keyword",
                    search_method="hybrid",
                    max_files=3,
                    enable_rerank=False,
                )
            )

    paths = {item.file_path for item in result.retrieved_files}
    assert "src/persistent_vector.py" in paths
    assert result.search_method == "hybrid"
    print("[OK] VECTOR_STORE_PROVIDER=pgvector 时 hybrid 会融合 pgvector 召回")

"""pgvector 向量持久化的轻量 SQL 构建器。

为什么先做 SQL 构建器，而不是立刻替换现有检索链路：
当前项目已经有稳定的本地 hybrid 检索。pgvector 是工程化增强，先把
schema、upsert、search 这些边界做清楚，再逐步接入在线检索更稳。
"""

from __future__ import annotations

import re
import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

SAFE_IDENTIFIER = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


@dataclass(frozen=True)
class PgVectorStoreConfig:
    table_name: str = "code_embeddings"
    embedding_dim: int = 1536
    index_lists: int = 100


@dataclass(frozen=True)
class CodeEmbeddingDocument:
    repo_url: str
    file_path: str
    chunk_id: str
    content: str
    embedding: list[float]
    metadata: dict[str, Any] | None = None

    @property
    def content_hash(self) -> str:
        return sha256(self.content.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PgVectorSearchHit:
    repo_url: str
    file_path: str
    chunk_id: str
    content: str
    metadata: dict[str, Any]
    score: float


def _safe_identifier(name: str) -> str:
    if not SAFE_IDENTIFIER.match(name):
        raise ValueError(f"非法 SQL 标识符：{name}")
    return name


def embedding_to_pgvector_literal(embedding: list[float]) -> str:
    """把 Python list 转成 pgvector 接受的 '[0.1,0.2]' 文本。"""
    if not embedding:
        raise ValueError("embedding 不能为空")
    return "[" + ",".join(f"{float(value):.8g}" for value in embedding) + "]"


def build_pgvector_schema_sql(config: PgVectorStoreConfig) -> list[str]:
    table = _safe_identifier(config.table_name)
    dim = int(config.embedding_dim)
    if dim <= 0:
        raise ValueError("embedding_dim 必须大于 0")
    lists = max(1, int(config.index_lists))

    return [
        "CREATE EXTENSION IF NOT EXISTS vector",
        f"""
CREATE TABLE IF NOT EXISTS {table} (
    id BIGSERIAL PRIMARY KEY,
    repo_url TEXT NOT NULL,
    file_path TEXT NOT NULL,
    chunk_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    content TEXT NOT NULL,
    embedding vector({dim}) NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (repo_url, file_path, chunk_id, content_hash)
)
""".strip(),
        f"""
CREATE INDEX IF NOT EXISTS ix_{table}_repo_path
ON {table} (repo_url, file_path)
""".strip(),
        f"""
CREATE INDEX IF NOT EXISTS ix_{table}_embedding_cosine
ON {table}
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = {lists})
""".strip(),
    ]


def build_pgvector_upsert_sql(config: PgVectorStoreConfig) -> str:
    table = _safe_identifier(config.table_name)
    return f"""
INSERT INTO {table} (
    repo_url,
    file_path,
    chunk_id,
    content_hash,
    content,
    embedding,
    metadata
) VALUES (
    :repo_url,
    :file_path,
    :chunk_id,
    :content_hash,
    :content,
    :embedding,
    CAST(:metadata AS jsonb)
)
ON CONFLICT (repo_url, file_path, chunk_id, content_hash)
DO UPDATE SET
    content = EXCLUDED.content,
    embedding = EXCLUDED.embedding,
    metadata = EXCLUDED.metadata,
    updated_at = now()
""".strip()


def build_pgvector_search_sql(config: PgVectorStoreConfig, limit: int = 8) -> str:
    table = _safe_identifier(config.table_name)
    safe_limit = min(max(int(limit), 1), 50)
    return f"""
SELECT
    repo_url,
    file_path,
    chunk_id,
    content,
    metadata,
    1 - (embedding <=> :embedding) AS score
FROM {table}
WHERE repo_url = :repo_url
ORDER BY embedding <=> :embedding
LIMIT {safe_limit}
""".strip()


def build_pgvector_search_params(repo_url: str, embedding: list[float]) -> dict[str, str]:
    return {
        "repo_url": repo_url,
        "embedding": embedding_to_pgvector_literal(embedding),
    }


def row_to_pgvector_hit(row: Any) -> PgVectorSearchHit:
    mapping = getattr(row, "_mapping", row)
    metadata = mapping["metadata"] or {}
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    return PgVectorSearchHit(
        repo_url=mapping["repo_url"],
        file_path=mapping["file_path"],
        chunk_id=mapping["chunk_id"],
        content=mapping["content"],
        metadata=metadata,
        score=float(mapping["score"]),
    )


def document_to_upsert_params(document: CodeEmbeddingDocument) -> dict[str, Any]:
    return {
        "repo_url": document.repo_url,
        "file_path": document.file_path,
        "chunk_id": document.chunk_id,
        "content_hash": document.content_hash,
        "content": document.content,
        "embedding": embedding_to_pgvector_literal(document.embedding),
        "metadata": json.dumps(document.metadata or {}, ensure_ascii=False),
    }

# backend/app/agents/code_retriever.py
#
# 作用：Code Retriever Agent —— 根据 issue 检索相关代码文件。
#
# 检索流程（语义模式，默认）：
# 1. 调用 build_code_index() 为 repo 建立 LlamaIndex 向量索引
# 2. 用 query_text（issue 完整文本）或 issue_summary 作为 query
# 3. semantic_search() 返回余弦相似度最高的 top-k 代码 chunk
# 4. 转换成 RetrievedFile 格式，返回给 Planner Agent
#
# 为什么不把整个 repo 塞给 LLM？
# - 大型仓库有几千个文件，几十万行代码
# - LLM 的 context window 有上限（如 DeepSeek 128K token）
# - 正确做法：先"检索"相关片段，再交给 LLM 分析
#
# 三种检索模式：
# - semantic（默认）：LlamaIndex 向量检索，找语义相近的代码
# - keyword：关键词字符串搜索，适合调试或 Embedding API 不可用时
# - hybrid：semantic + keyword + BM25 三路候选，再用 RRF 融合排序

import logging
import os
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from sqlalchemy import create_engine, text

try:
    from rank_bm25 import BM25Okapi
except ImportError:  # pragma: no cover - 本地没装依赖时走内置兜底，测试仍可运行。
    BM25Okapi = None

from app.core.config import get_settings
from app.core.llm_trace import record_token_usage
from app.schemas.code_retrieval import (
    CodeRetrievalRequest,
    CodeRetrievalResult,
    RetrievedFile,
)
from app.tools.semantic_search_tool import (
    IGNORED_DIRS,
    MAX_FILE_SIZE_BYTES,
    SEARCHABLE_EXTENSIONS,
    build_code_index,
    semantic_search,
)
from app.services.vector_store import (
    PgVectorStoreConfig,
    build_pgvector_search_params,
    build_pgvector_search_sql,
    row_to_pgvector_hit,
)

logger = logging.getLogger(__name__)


# ── 语义检索（主路径）────────────────────────────────────────────────────────


def _retrieve_semantic(request: CodeRetrievalRequest) -> CodeRetrievalResult:
    """
    使用 LlamaIndex 语义检索找到与 issue 最相关的代码 chunk。

    参数:
        request: 包含 repo_path 和 query_text / issue_summary

    返回:
        CodeRetrievalResult，search_method="semantic"
    """
    repo_path = Path(request.repo_path)

    # 确定 query：优先用完整 issue 文本，其次用摘要；再经过 Query Rewrite 降噪。
    raw_query = request.query_text or request.issue_summary
    query = rewrite_retrieval_query(
        query_text=request.query_text,
        issue_summary=request.issue_summary,
        keywords=request.keywords,
    )
    if not query:
        logger.warning("未提供 query_text 或 issue_summary，无法进行语义检索")
        return CodeRetrievalResult(
            retrieved_files=[],
            total_searched_files=0,
            keywords_used=[],
            query_text_used=None,
            query_rewritten=False,
            search_method="semantic",
        )

    preview = query[:80] + "..." if len(query) > 80 else query
    logger.info(f"语义检索开始：repo={repo_path.name}, query='{preview}'")

    # 缓存目录放在 repo 同级，避免污染仓库本身
    cache_dir = repo_path.parent / ".llamaindex_cache"
    index = build_code_index(repo_path=repo_path, cache_dir=cache_dir)

    raw_results = semantic_search(
        index=index,
        query_text=query,
        top_k=request.max_files,
    )

    retrieved_files = [
        RetrievedFile(
            file_path=item["file_path"],
            line_start=item["line_start"],
            line_end=item["line_end"],
            snippet=item["snippet"],
            score=item["score"],
            method="semantic",
        )
        for item in raw_results
    ]

    reranked = False
    if request.enable_rerank:
        retrieved_files, reranked = rerank_retrieved_files(
            query_text=query,
            retrieved_files=retrieved_files,
            max_files=request.max_files,
        )
    else:
        retrieved_files = retrieved_files[: request.max_files]

    logger.info(f"语义检索完成：返回 {len(retrieved_files)} 个代码片段")

    return CodeRetrievalResult(
        retrieved_files=retrieved_files,
        total_searched_files=0,   # 语义检索不统计扫描文件数
        keywords_used=[],
        query_text_used=query,
        query_rewritten=query != (raw_query or ""),
        reranked=reranked,
        rerank_method="llm" if reranked else None,
        search_method="semantic",
    )


# ── 关键词检索（备用路径）────────────────────────────────────────────────────


# 英文停用词：太通用，搜索价值低
_STOP_WORDS: set[str] = {
    "the", "and", "for", "are", "but", "not", "you", "all",
    "can", "her", "was", "one", "our", "out", "day", "get",
    "has", "him", "his", "how", "man", "new", "now", "old",
    "see", "two", "way", "who", "boy", "did", "its", "let",
    "put", "say", "she", "too", "use", "with", "this", "that",
    "have", "from", "they", "will", "been", "when", "what",
    "said", "each", "which", "their", "time", "will", "about",
    "there", "could", "other", "into", "then", "than", "these",
    "some", "would", "make", "like", "him", "into", "time",
    "error", "issue", "should", "does", "also", "after", "before",
    "return", "value", "param", "args", "kwargs", "self", "cls",
    "true", "false", "none", "null", "undefined",
}


_RRF_K = 60


def _collect_searchable_files(repo_path: Path) -> list[Path]:
    """
    收集可检索代码文件。

    keyword 和 BM25 都要扫描本地文件，单独抽成函数可以避免两处规则不一致。
    """

    all_files: list[Path] = []
    for root, dirs, filenames in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        for filename in filenames:
            fp = Path(root) / filename
            if fp.suffix.lower() not in SEARCHABLE_EXTENSIONS:
                continue
            try:
                if fp.stat().st_size > MAX_FILE_SIZE_BYTES:
                    continue
            except OSError:
                continue
            all_files.append(fp)
    return all_files


def _build_local_search_corpus(repo_path: Path) -> tuple[list[tuple[Path, str, list[str]]], int]:
    """
    一次性读取本地检索需要的文件内容。

    hybrid 检索同时需要 keyword 和 BM25。把文件读取集中到这里，可以避免同一个文件
    被重复打开两次，仓库稍大时会明显减少磁盘 IO。
    """

    all_files = _collect_searchable_files(repo_path)
    corpus: list[tuple[Path, str, list[str]]] = []
    for file_path in all_files:
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            logger.warning(f"无法读取文件 {file_path}：{exc}")
            continue
        corpus.append((file_path, content, _tokenize_for_bm25(content)))
    return corpus, len(all_files)


def _split_identifier(term: str) -> list[str]:
    """把 parse_user_input / ParseUserInput 拆成更容易命中的检索词。"""

    pieces: list[str] = []
    for part in re.split(r"[_\W]+", term):
        if not part:
            continue
        pieces.append(part)
        pieces.extend(re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|\d+", part))
    return pieces


def _tokenize_for_bm25(text: str) -> list[str]:
    """
    把代码或 issue 文本切成 BM25 token。

    BM25 是一种稀疏检索算法，它看重“词在本文档里多、在其他文档里少”这种信号。
    """

    tokens: list[str] = []
    for raw in re.findall(r"[A-Za-z_][A-Za-z0-9_]{1,120}|\d+", text):
        for piece in [raw, *_split_identifier(raw)]:
            token = piece.lower()
            if len(token) < 2 or token in _STOP_WORDS:
                continue
            tokens.append(token)
    return tokens


def _local_bm25_scores(
    tokenized_documents: list[list[str]],
    query_tokens: list[str],
    *,
    k1: float = 1.5,
    b: float = 0.75,
) -> list[float]:
    """
    rank-bm25 没安装时的轻量兜底实现。

    这样做的原因是：项目依赖里会声明 rank-bm25，但本地测试环境可能还没重新安装依赖；
    兜底实现能保证单测不因为缺包而失败。
    """

    if not tokenized_documents or not query_tokens:
        return [0.0 for _ in tokenized_documents]

    total_docs = len(tokenized_documents)
    doc_lengths = [len(doc) for doc in tokenized_documents]
    avg_doc_len = sum(doc_lengths) / total_docs if total_docs else 0.0
    term_doc_counts: Counter[str] = Counter()
    doc_term_counts: list[Counter[str]] = []

    for doc in tokenized_documents:
        counts = Counter(doc)
        doc_term_counts.append(counts)
        term_doc_counts.update(counts.keys())

    unique_query_tokens = list(dict.fromkeys(query_tokens))
    scores: list[float] = []
    for index, counts in enumerate(doc_term_counts):
        doc_len = doc_lengths[index] or 1
        score = 0.0
        for token in unique_query_tokens:
            term_frequency = counts.get(token, 0)
            if term_frequency == 0:
                continue
            docs_with_term = term_doc_counts[token]
            idf = math.log(1 + (total_docs - docs_with_term + 0.5) / (docs_with_term + 0.5))
            denominator = term_frequency + k1 * (1 - b + b * doc_len / (avg_doc_len or 1))
            score += idf * (term_frequency * (k1 + 1)) / denominator
        scores.append(score)
    return scores


def _bm25_scores(tokenized_documents: list[list[str]], query_tokens: list[str]) -> list[float]:
    if BM25Okapi is not None:
        return [float(score) for score in BM25Okapi(tokenized_documents).get_scores(query_tokens)]
    return _local_bm25_scores(tokenized_documents, query_tokens)


def _snippet_around_terms(
    content: str,
    query_tokens: list[str],
    max_snippet_lines: int,
) -> tuple[int, int, str]:
    """返回第一个 BM25 token 命中的附近代码片段。"""

    lines = content.splitlines()
    token_set = set(query_tokens)
    first_hit = 0
    for index, line in enumerate(lines):
        if token_set.intersection(_tokenize_for_bm25(line)):
            first_hit = index
            break

    snippet_start = max(0, first_hit - 5)
    snippet_end = min(len(lines), snippet_start + max_snippet_lines)
    return snippet_start + 1, snippet_end, "\n".join(lines[snippet_start:snippet_end])


def _retrieve_bm25_candidates(
    repo_path: Path,
    query_text: str,
    keywords: list[str],
    max_files: int,
    max_snippet_lines: int,
    corpus: list[tuple[Path, str, list[str]]] | None = None,
    total_files: int | None = None,
) -> tuple[list[RetrievedFile], int]:
    """
    使用 BM25 做本地稀疏检索，作为 hybrid 的第三路信号。

    它不需要 Embedding API，适合补足语义检索漏掉的文件名、函数名、错误名等精确线索。
    """

    query_tokens = _tokenize_for_bm25(" ".join([query_text, *keywords]))
    if not query_tokens:
        return [], 0

    if corpus is None:
        corpus, scanned_files = _build_local_search_corpus(repo_path)
    else:
        scanned_files = total_files if total_files is not None else len(corpus)

    documents: list[tuple[Path, str, list[str]]] = []
    for file_path, content, tokens in corpus:
        if tokens:
            documents.append((file_path, content, tokens))

    scores = _bm25_scores([tokens for _, _, tokens in documents], query_tokens)
    scored_documents = [
        (score, file_path, content)
        for (file_path, content, _), score in zip(documents, scores)
        if score > 0
    ]
    scored_documents.sort(key=lambda item: item[0], reverse=True)

    results: list[RetrievedFile] = []
    for score, file_path, content in scored_documents[:max_files]:
        line_start, line_end, snippet = _snippet_around_terms(
            content=content,
            query_tokens=query_tokens,
            max_snippet_lines=max_snippet_lines,
        )
        try:
            relative_path = str(file_path.relative_to(repo_path)).replace("\\", "/")
        except ValueError:
            relative_path = str(file_path)
        results.append(
            RetrievedFile(
                file_path=relative_path,
                line_start=line_start,
                line_end=line_end,
                snippet=snippet,
                matched_keywords=list(dict.fromkeys(query_tokens))[:15],
                score=score,
                method="keyword",
            )
        )
    return results, scanned_files


def _rrf_fuse_results(
    ranked_groups: list[list[RetrievedFile]],
    max_files: int,
) -> list[RetrievedFile]:
    """
    使用 RRF 融合多路检索结果。

    RRF（Reciprocal Rank Fusion）只看每个结果在各路排序里的名次，能避免 semantic
    的 0~1 分数和 keyword/BM25 的自定义分数无法直接比较。
    """

    fused_scores: dict[str, float] = {}
    best_items: dict[str, RetrievedFile] = {}

    for group in ranked_groups:
        for rank, item in enumerate(group, start=1):
            key = item.file_path
            fused_scores[key] = fused_scores.get(key, 0.0) + 1.0 / (_RRF_K + rank)
            if key not in best_items or item.method == "semantic":
                best_items[key] = item

    ordered_paths = sorted(
        fused_scores,
        key=lambda path: (fused_scores[path], best_items[path].score),
        reverse=True,
    )
    return [
        best_items[path].model_copy(
            update={
                "score": round(fused_scores[path], 6),
                "method": "hybrid",
            }
        )
        for path in ordered_paths[:max_files]
    ]


def extract_keywords_from_issue(
    issue_text: str,
    issue_analysis: Optional[dict] = None,
) -> List[str]:
    """
    从 issue 文本和分析结果中提取搜索关键词。

    提取策略：
    1. 从 issue_analysis 里取 summary、acceptance_criteria
    2. 从 issue_text 里提取"看起来像代码标识符"的词（驼峰、下划线命名）
    3. 合并去重，过滤太短或太通用的词

    参数:
        issue_text: 原始 issue 文本
        issue_analysis: Issue Analyst 的分析结果（dict 格式，可选）

    返回:
        关键词列表（最多 15 个，按长度降序排列）
    """
    keywords: set[str] = set()

    if issue_analysis:
        summary = issue_analysis.get("summary", "")
        for word in summary.split():
            cleaned = word.strip(".,;:!?()'\"")
            if len(cleaned) >= 3:
                keywords.add(cleaned)

        for criterion in issue_analysis.get("acceptance_criteria", []):
            for word in criterion.split():
                cleaned = word.strip(".,;:!?()'\"")
                if len(cleaned) >= 3:
                    keywords.add(cleaned)

    # 提取"代码风格"的词（函数名、变量名、类名等标识符模式）
    code_identifiers = re.findall(r'\b[a-zA-Z][a-zA-Z0-9_]{2,}\b', issue_text)
    for identifier in code_identifiers:
        if identifier.lower() not in _STOP_WORDS:
            keywords.add(identifier)

    filtered = [k for k in keywords if len(k) >= 3]
    filtered.sort(key=len, reverse=True)

    logger.info(f"提取到 {len(filtered)} 个关键词：{filtered[:10]}")
    return filtered[:15]


_CODE_SPAN_RE = re.compile(r"`([^`]{2,120})`")
_ERROR_NAME_RE = re.compile(r"\b[A-Z][A-Za-z0-9_]*(?:Error|Exception|Warning)\b")
_FILE_REF_RE = re.compile(
    r"\b[\w./\\-]+\.(?:py|js|jsx|ts|tsx|go|java|rs|rb|php|c|cpp|h|hpp)(?::\d+)?\b"
)
_IDENTIFIER_RE = re.compile(r"\b[a-zA-Z_][a-zA-Z0-9_]{2,}\b")


def _clean_query_term(term: str) -> str:
    return term.strip(" \t\r\n.,;:!?()[]{}'\"")


def _append_unique(target: list[str], seen: set[str], term: str) -> None:
    cleaned = _clean_query_term(term)
    if not cleaned:
        return
    key = cleaned.lower()
    if key in seen:
        return
    seen.add(key)
    target.append(cleaned)


def rewrite_retrieval_query(
    query_text: Optional[str],
    issue_summary: Optional[str] = None,
    keywords: Optional[list[str]] = None,
    *,
    max_terms: int = 24,
) -> str:
    """
    将用户 issue 改写成更适合代码检索的 query（RAG Query Rewrite）。

    这个版本先用确定性规则，不调用 LLM：
    - 保留 issue 摘要，减少原文中的寒暄和长句噪音
    - 提取反引号里的符号、错误类型、文件路径和代码标识符
    - 合并关键词检索已有的 keywords，方便 semantic / hybrid 共用
    """

    raw_text = (query_text or "").strip()
    summary = (issue_summary or "").strip()
    if not raw_text and not summary:
        return ""

    source = "\n".join(part for part in [summary, raw_text] if part)
    terms: list[str] = []
    seen: set[str] = set()

    for term in _CODE_SPAN_RE.findall(source):
        _append_unique(terms, seen, term)
    for term in _ERROR_NAME_RE.findall(source):
        _append_unique(terms, seen, term)
    for term in _FILE_REF_RE.findall(source):
        _append_unique(terms, seen, term)
    for term in keywords or []:
        _append_unique(terms, seen, term)

    for term in _IDENTIFIER_RE.findall(source):
        lowered = term.lower()
        if lowered in _STOP_WORDS or lowered.isdigit():
            continue
        if len(term) < 4 and "_" not in term:
            continue
        # 驼峰、下划线和异常名更像代码符号，优先保留。
        if "_" in term or any(ch.isupper() for ch in term[1:]):
            _append_unique(terms, seen, term)
        elif len(terms) < max_terms // 2:
            _append_unique(terms, seen, term)
        if len(terms) >= max_terms:
            break

    base = summary or raw_text.splitlines()[0]
    base = base[:240]
    if terms:
        return f"{base}\nRelevant code terms: {', '.join(terms[:max_terms])}"
    return base


RERANK_PROMPT = """你是代码检索结果排序器。

请根据 Issue Query 判断哪些代码片段最可能帮助修复问题。
只输出 JSON，不要输出 Markdown。

输出格式：
{{
  "ranked_indices": [1, 3, 2],
  "reason": "一句话说明排序依据"
}}

规则：
- ranked_indices 使用候选编号，从 1 开始。
- 只返回候选中真实存在的编号。
- 越相关的编号越靠前。"""


def _extract_json_object(content: str) -> dict:
    """从 LLM 文本中提取 JSON 对象。"""

    raw = content.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        end = -1 if lines and lines[-1].strip() == "```" else len(lines)
        raw = "\n".join(lines[1:end]).strip()

    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        raw = raw[start : end + 1]
    return json.loads(raw)


def _build_rerank_candidates(files: list[RetrievedFile]) -> str:
    """把检索结果压缩成 LLM 容易比较的候选列表。"""

    chunks: list[str] = []
    for idx, item in enumerate(files, 1):
        snippet = "\n".join(item.snippet.splitlines()[:20])
        chunks.append(
            f"候选 {idx}\n"
            f"文件：{item.file_path}\n"
            f"行号：{item.line_start}-{item.line_end}\n"
            f"原始分数：{item.score}\n"
            f"代码片段：\n{snippet}"
        )
    return "\n\n".join(chunks)


def _order_by_ranked_indices(
    files: list[RetrievedFile],
    ranked_indices: list[int],
    max_files: int,
) -> list[RetrievedFile]:
    """根据 LLM 返回的编号排序，漏掉的候选按原顺序追加。"""

    ordered: list[RetrievedFile] = []
    used: set[int] = set()
    for index in ranked_indices:
        zero_based = index - 1
        if 0 <= zero_based < len(files) and zero_based not in used:
            ordered.append(files[zero_based])
            used.add(zero_based)

    for index, item in enumerate(files):
        if index not in used:
            ordered.append(item)

    return ordered[:max_files]


def rerank_retrieved_files(
    query_text: str,
    retrieved_files: list[RetrievedFile],
    max_files: int,
) -> tuple[list[RetrievedFile], bool]:
    """
    使用 LLM 对初筛代码片段重新排序。

    Rerank 是“二次排序”：先由 semantic / hybrid 找到候选，再让 LLM
    根据 issue 语义判断哪些片段更值得 Planner 阅读。
    """

    if len(retrieved_files) < 2 or not query_text.strip():
        return retrieved_files[:max_files], False

    settings = get_settings()
    llm = ChatOpenAI(
        model=settings.model_name,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        temperature=0,
        request_timeout=120,
        max_retries=1,
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", RERANK_PROMPT),
        (
            "human",
            "Issue Query:\n{query_text}\n\n候选代码片段：\n{candidates}",
        ),
    ])

    try:
        messages = prompt.format_messages(
            query_text=query_text,
            candidates=_build_rerank_candidates(retrieved_files),
        )
        response = llm.invoke(messages)
        record_token_usage(response)
        data = _extract_json_object(response.content)
        ranked_indices = data.get("ranked_indices")
        if not isinstance(ranked_indices, list):
            raise ValueError("ranked_indices 不是列表")
        valid_indices = [int(item) for item in ranked_indices]
        return _order_by_ranked_indices(retrieved_files, valid_indices, max_files), True
    except Exception as exc:
        logger.warning(f"LLM Rerank 失败，保留原始排序：{exc}")
        return retrieved_files[:max_files], False


def _search_content_for_keywords(
    file_path: Path,
    repo_path: Path,
    content: str,
    keywords: List[str],
    max_snippet_lines: int,
) -> Tuple[float, Optional[RetrievedFile]]:
    """
    在已读取的文件内容里搜索关键词，返回相关度评分和文件信息。

    这样拆分的原因是：hybrid 模式已经为了 BM25 读取过文件内容，关键词检索可以复用，
    不必再从磁盘读一遍。
    """
    lines = content.splitlines()
    keywords_lower = [k.lower() for k in keywords]

    # 找出所有命中行
    hit_lines: Dict[int, List[str]] = {}
    for line_idx, line in enumerate(lines):
        line_lower = line.lower()
        matched = [
            keywords[i]
            for i, kw in enumerate(keywords_lower)
            if kw in line_lower
        ]
        if matched:
            hit_lines[line_idx] = matched

    if not hit_lines:
        return 0.0, None

    all_matched_keywords: set[str] = set()
    for matched in hit_lines.values():
        all_matched_keywords.update(matched)

    score = (
        len(all_matched_keywords) * 20.0
        + min(len(hit_lines), 5) * 5.0
    )

    first_hit_line = min(hit_lines.keys())
    snippet_start = max(0, first_hit_line - 5)
    snippet_end = min(len(lines), snippet_start + max_snippet_lines)
    snippet = "\n".join(lines[snippet_start:snippet_end])

    try:
        relative_path = str(file_path.relative_to(repo_path)).replace("\\", "/")
    except ValueError:
        relative_path = str(file_path)

    result = RetrievedFile(
        file_path=relative_path,
        line_start=snippet_start + 1,
        line_end=snippet_start + (snippet_end - snippet_start),
        snippet=snippet,
        matched_keywords=list(all_matched_keywords),
        score=score,
        method="keyword",
    )

    return score, result


def _search_file_for_keywords(
    file_path: Path,
    repo_path: Path,
    keywords: List[str],
    max_snippet_lines: int,
) -> Tuple[float, Optional[RetrievedFile]]:
    """读取单个文件并执行关键词检索，供 keyword 独立模式使用。"""

    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
    except OSError as e:
        logger.warning(f"无法读取文件 {file_path}：{e}")
        return 0.0, None
    return _search_content_for_keywords(
        file_path=file_path,
        repo_path=repo_path,
        content=content,
        keywords=keywords,
        max_snippet_lines=max_snippet_lines,
    )


def _keyword_candidates_from_corpus(
    *,
    repo_path: Path,
    corpus: list[tuple[Path, str, list[str]]],
    keywords: list[str],
    max_files: int,
    max_snippet_lines: int,
) -> list[RetrievedFile]:
    """从已读取的本地语料中生成 keyword 候选，避免 hybrid 模式重复读文件。"""

    scored: list[tuple[float, RetrievedFile]] = []
    for file_path, content, _tokens in corpus:
        score, result = _search_content_for_keywords(
            file_path=file_path,
            repo_path=repo_path,
            content=content,
            keywords=keywords,
            max_snippet_lines=max_snippet_lines,
        )
        if result is not None and score > 0:
            scored.append((score, result))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [result for _, result in scored[:max_files]]


def _retrieve_keyword(request: CodeRetrievalRequest) -> CodeRetrievalResult:
    """
    使用关键词搜索找到相关代码文件（备用模式）。

    适合 Embedding API 不可用、需要精确字符串匹配的场景。

    参数:
        request: 包含 repo_path 和 keywords

    返回:
        CodeRetrievalResult，search_method="keyword"
    """
    repo_path = Path(request.repo_path)

    keywords = request.keywords or extract_keywords_from_issue(
        request.query_text or request.issue_summary or ""
    )

    if not keywords:
        logger.warning("关键词列表为空，无法进行关键词检索")
        return CodeRetrievalResult(
            retrieved_files=[],
            total_searched_files=0,
            keywords_used=[],
            query_text_used=None,
            query_rewritten=False,
            search_method="keyword",
        )

    # 收集所有可搜索文件。这里复用 BM25 的扫描规则，避免两种本地检索看到的文件范围不同。
    all_files = _collect_searchable_files(repo_path)

    logger.info(f"关键词检索：扫描 {len(all_files)} 个文件")

    scored: List[Tuple[float, RetrievedFile]] = []
    for file_path in all_files:
        score, result = _search_file_for_keywords(
            file_path=file_path,
            repo_path=repo_path,
            keywords=keywords,
            max_snippet_lines=request.max_snippet_lines,
        )
        if result is not None and score > 0:
            scored.append((score, result))

    scored.sort(key=lambda x: x[0], reverse=True)
    top_results = [r for _, r in scored[: request.max_files]]

    logger.info(f"关键词检索完成：命中 {len(scored)} 个文件，返回 top-{len(top_results)}")

    return CodeRetrievalResult(
        retrieved_files=top_results,
        total_searched_files=len(all_files),
        keywords_used=keywords,
        query_text_used=None,
        query_rewritten=False,
        search_method="keyword",
    )


# ── pgvector 检索（持久化向量库路径）────────────────────────────────────────────


def _pgvector_repo_key(request: CodeRetrievalRequest) -> str:
    """pgvector 表用 repo_url 分组；没有 URL 时用本地 repo_path 兜底。"""
    return request.repo_url or request.repo_path


def _embed_query_for_pgvector(query: str) -> list[float]:
    settings = get_settings()
    embedder = OpenAIEmbeddings(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        model="text-embedding-3-small",
    )
    return list(embedder.embed_query(query))


def _retrieve_pgvector(request: CodeRetrievalRequest) -> CodeRetrievalResult:
    """
    从 PostgreSQL pgvector 表里检索代码 chunk。

    这条路径解决“向量索引是否持久化”的面试追问。它不会替代本地 hybrid，
    而是可以作为 hybrid 的第四路候选，或者单独 `search_method=pgvector` 调试。
    """
    raw_query = request.query_text or request.issue_summary
    query = rewrite_retrieval_query(
        query_text=request.query_text,
        issue_summary=request.issue_summary,
        keywords=request.keywords,
    )
    if not query:
        return CodeRetrievalResult(
            retrieved_files=[],
            total_searched_files=0,
            keywords_used=request.keywords,
            query_text_used=None,
            query_rewritten=False,
            search_method="pgvector",
        )

    settings = get_settings()
    config = PgVectorStoreConfig(
        table_name=settings.pgvector_table_name,
        embedding_dim=settings.pgvector_embedding_dim,
    )
    repo_key = _pgvector_repo_key(request)

    try:
        embedding = _embed_query_for_pgvector(query)
        sql = build_pgvector_search_sql(config, limit=request.max_files)
        params = build_pgvector_search_params(repo_url=repo_key, embedding=embedding)
        engine = create_engine(settings.database_url_sync)
        try:
            with engine.connect() as conn:
                rows = conn.execute(text(sql), params).fetchall()
        finally:
            engine.dispose()
    except Exception as exc:
        logger.warning("pgvector 检索失败，返回空结果：%s", exc)
        rows = []

    retrieved_files: list[RetrievedFile] = []
    for row in rows:
        hit = row_to_pgvector_hit(row)
        line_start = int(hit.metadata.get("line_start") or 1)
        line_end = int(
            hit.metadata.get("line_end")
            or max(line_start, line_start + len(hit.content.splitlines()) - 1)
        )
        retrieved_files.append(
            RetrievedFile(
                file_path=hit.file_path,
                line_start=line_start,
                line_end=line_end,
                snippet=hit.content,
                matched_keywords=[],
                score=hit.score,
                method="pgvector",
            )
        )

    logger.info("pgvector 检索完成：repo=%s, hits=%s", repo_key, len(retrieved_files))
    return CodeRetrievalResult(
        retrieved_files=retrieved_files[: request.max_files],
        total_searched_files=len(retrieved_files),
        keywords_used=request.keywords,
        query_text_used=query,
        query_rewritten=query != (raw_query or ""),
        reranked=False,
        rerank_method=None,
        search_method="pgvector",
    )


# ── 混合检索（合并去重）────────────────────────────────────────────────────────


def _retrieve_hybrid(request: CodeRetrievalRequest) -> CodeRetrievalResult:
    """
    混合检索：同时跑语义检索、关键词检索和 BM25 稀疏检索，再用 RRF 融合排序。

    合并策略：
    - BM25 补足精确代码符号、错误名、文件名这类线索
    - RRF 只比较每一路的名次，不直接混用不同算法的原始分数

    参数:
        request: 同时包含 query_text 和 keywords

    返回:
        CodeRetrievalResult，search_method="hybrid"
    """
    keywords = request.keywords or extract_keywords_from_issue(
        request.query_text or request.issue_summary or ""
    )
    rewritten_request = request.model_copy(
        update={"keywords": keywords, "enable_rerank": False}
    )
    semantic_result = _retrieve_semantic(rewritten_request)
    repo_path = Path(request.repo_path)
    local_corpus, local_total = _build_local_search_corpus(repo_path)
    keyword_files = _keyword_candidates_from_corpus(
        repo_path=repo_path,
        corpus=local_corpus,
        keywords=keywords,
        max_files=request.max_files,
        max_snippet_lines=request.max_snippet_lines,
    )
    bm25_results, bm25_total = _retrieve_bm25_candidates(
        repo_path=repo_path,
        query_text=semantic_result.query_text_used or request.query_text or request.issue_summary or "",
        keywords=keywords,
        max_files=max(request.max_files * 2, request.max_files),
        max_snippet_lines=request.max_snippet_lines,
        corpus=local_corpus,
        total_files=local_total,
    )
    pgvector_files: list[RetrievedFile] = []
    settings = get_settings()
    if settings.vector_store_provider.lower() == "pgvector":
        pgvector_result = _retrieve_pgvector(
            request.model_copy(update={"enable_rerank": False})
        )
        pgvector_files = pgvector_result.retrieved_files

    merged = _rrf_fuse_results(
        [
            semantic_result.retrieved_files,
            keyword_files,
            bm25_results,
            pgvector_files,
        ],
        max_files=max(request.max_files * 2, request.max_files),
    )

    reranked = False
    if request.enable_rerank:
        merged, reranked = rerank_retrieved_files(
            query_text=semantic_result.query_text_used or request.query_text or "",
            retrieved_files=merged,
            max_files=request.max_files,
        )
    else:
        merged = merged[: request.max_files]

    logger.info(
        f"混合检索完成：semantic={len(semantic_result.retrieved_files)} 个，"
        f"keyword={len(keyword_files)} 个，"
        f"bm25={len(bm25_results)} 个，"
        f"pgvector={len(pgvector_files)} 个，"
        f"合并后={len(merged)} 个"
    )

    return CodeRetrievalResult(
        retrieved_files=merged,
        total_searched_files=max(local_total, bm25_total),
        keywords_used=keywords,
        query_text_used=semantic_result.query_text_used,
        query_rewritten=semantic_result.query_rewritten,
        reranked=reranked,
        rerank_method="llm" if reranked else "rrf",
        search_method="hybrid",
    )


# ── 公开入口 ──────────────────────────────────────────────────────────────────


def retrieve_code(request: CodeRetrievalRequest) -> CodeRetrievalResult:
    """
    代码检索主入口，根据 request.search_method 分发到不同检索策略。

    默认使用 semantic（语义检索）。

    参数:
        request: CodeRetrievalRequest

    返回:
        CodeRetrievalResult

    异常:
        FileNotFoundError: 仓库路径不存在
        ValueError: 没有可索引文件（语义检索时）
    """
    repo_path = Path(request.repo_path)
    if not repo_path.exists():
        raise FileNotFoundError(f"仓库路径不存在：{repo_path}")

    method = request.search_method

    if method == "semantic":
        return _retrieve_semantic(request)
    elif method == "keyword":
        return _retrieve_keyword(request)
    elif method == "pgvector":
        return _retrieve_pgvector(request)
    elif method == "hybrid":
        return _retrieve_hybrid(request)
    else:
        logger.warning(f"未知检索模式 '{method}'，回退到语义检索")
        return _retrieve_semantic(request)

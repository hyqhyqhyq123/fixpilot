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
# - hybrid：两者结果合并去重，精度最高

import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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

    # 确定 query：优先用完整 issue 文本，其次用摘要
    query = request.query_text or request.issue_summary
    if not query:
        logger.warning("未提供 query_text 或 issue_summary，无法进行语义检索")
        return CodeRetrievalResult(
            retrieved_files=[],
            total_searched_files=0,
            keywords_used=[],
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

    logger.info(f"语义检索完成：返回 {len(retrieved_files)} 个代码片段")

    return CodeRetrievalResult(
        retrieved_files=retrieved_files,
        total_searched_files=0,   # 语义检索不统计扫描文件数
        keywords_used=[],
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


def _search_file_for_keywords(
    file_path: Path,
    repo_path: Path,
    keywords: List[str],
    max_snippet_lines: int,
) -> Tuple[float, Optional[RetrievedFile]]:
    """
    在单个文件里搜索关键词，返回相关度评分和文件信息。

    参数:
        file_path: 要搜索的文件
        repo_path: 仓库根目录
        keywords: 关键词列表
        max_snippet_lines: 每个文件最多返回多少行

    返回:
        (score, RetrievedFile | None)，score=0 表示未命中
    """
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
    except OSError as e:
        logger.warning(f"无法读取文件 {file_path}：{e}")
        return 0.0, None

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

    if not request.keywords:
        logger.warning("关键词列表为空，无法进行关键词检索")
        return CodeRetrievalResult(
            retrieved_files=[],
            total_searched_files=0,
            keywords_used=[],
            search_method="keyword",
        )

    # 收集所有可搜索文件
    all_files: List[Path] = []
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

    logger.info(f"关键词检索：扫描 {len(all_files)} 个文件")

    scored: List[Tuple[float, RetrievedFile]] = []
    for file_path in all_files:
        score, result = _search_file_for_keywords(
            file_path=file_path,
            repo_path=repo_path,
            keywords=request.keywords,
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
        keywords_used=request.keywords,
        search_method="keyword",
    )


# ── 混合检索（合并去重）────────────────────────────────────────────────────────


def _retrieve_hybrid(request: CodeRetrievalRequest) -> CodeRetrievalResult:
    """
    混合检索：同时跑语义检索和关键词检索，结果合并去重。

    合并策略：
    - 按 file_path 去重，优先保留语义检索的结果（score 更可靠）
    - 排序：semantic 结果在前，keyword 结果在后

    参数:
        request: 同时包含 query_text 和 keywords

    返回:
        CodeRetrievalResult，search_method="hybrid"
    """
    semantic_result = _retrieve_semantic(request)
    keyword_result = _retrieve_keyword(request)

    # 以 file_path 去重，semantic 优先
    seen_paths: set[str] = set()
    merged: List[RetrievedFile] = []

    for f in semantic_result.retrieved_files:
        if f.file_path not in seen_paths:
            seen_paths.add(f.file_path)
            merged.append(f)

    for f in keyword_result.retrieved_files:
        if f.file_path not in seen_paths:
            seen_paths.add(f.file_path)
            merged.append(f)

    merged = merged[: request.max_files]

    logger.info(
        f"混合检索完成：semantic={len(semantic_result.retrieved_files)} 个，"
        f"keyword={len(keyword_result.retrieved_files)} 个，"
        f"合并后={len(merged)} 个"
    )

    return CodeRetrievalResult(
        retrieved_files=merged,
        total_searched_files=keyword_result.total_searched_files,
        keywords_used=request.keywords,
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
    elif method == "hybrid":
        return _retrieve_hybrid(request)
    else:
        logger.warning(f"未知检索模式 '{method}'，回退到语义检索")
        return _retrieve_semantic(request)

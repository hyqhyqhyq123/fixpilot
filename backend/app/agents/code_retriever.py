# backend/app/agents/code_retriever.py
# 作用：Code Retriever Agent —— 根据 issue 关键词搜索相关代码文件
#
# 为什么不把整个 repo 塞给 LLM？
# - 大型仓库有几千个文件，几十万行代码
# - LLM 的 context window 有上限（比如 DeepSeek 128K token）
# - 把全部代码塞进去既浪费 token 又容易干扰 LLM 的注意力
# - 正确做法：先"检索"相关片段，再交给 LLM 分析
#
# MVP 阶段：用关键词搜索（简单、快、无需额外依赖）
# 未来阶段：可以换成 LlamaIndex 语义搜索（更智能）
#
# 关键词搜索 vs 语义搜索：
# - 关键词搜索：直接在文件内容里找字符串，快但靠关键词质量
# - 语义搜索：把代码向量化，找"含义相近"的片段，慢但准确

import logging
import os
from pathlib import Path
from typing import List, Tuple

from app.schemas.code_retrieval import (
    CodeRetrievalRequest,
    CodeRetrievalResult,
    RetrievedFile,
)

logger = logging.getLogger(__name__)

# 只搜索这些扩展名的文件（避免在二进制文件里搜索）
SEARCHABLE_EXTENSIONS: set[str] = {
    ".py", ".js", ".ts", ".tsx", ".jsx",
    ".go", ".java", ".rs", ".rb", ".php",
    ".c", ".cpp", ".h", ".hpp",
    ".cs", ".swift", ".kt",
    ".md", ".txt", ".yaml", ".yml", ".toml", ".cfg", ".ini",
    ".json", ".xml", ".html", ".css", ".scss",
    ".sh", ".bash", ".zsh",
    ".sql",
}

# 跳过这些目录（和 repo_analysis_tool.py 里的过滤规则保持一致）
IGNORED_DIRS: set[str] = {
    ".git", ".svn", "node_modules", "vendor",
    ".venv", "venv", "env", "__pycache__",
    "dist", "build", "out", "target", ".next",
    ".tox", ".eggs", "htmlcov",
}

# 单个文件最大读取大小（字节）：超过此大小的文件跳过
# 避免读取几 MB 的大文件，消耗太多内存和时间
MAX_FILE_SIZE_BYTES = 512 * 1024  # 512 KB


def extract_keywords_from_issue(
    issue_text: str,
    issue_analysis: dict | None = None,
) -> List[str]:
    """
    从 issue 文本和分析结果中提取搜索关键词。

    提取策略：
    1. 从 issue_analysis 里取 summary、acceptance_criteria
    2. 从 issue_text 里提取"看起来像代码标识符"的词（驼峰、下划线命名）
    3. 合并去重，过滤太短或太通用的词

    参数:
        issue_text: 原始 issue 文本
        issue_analysis: Issue Analyst 的分析结果（dict 格式）

    返回:
        关键词列表（最多 15 个）
    """
    keywords: set[str] = set()

    # ── 从 issue_analysis 里提取结构化关键词 ──
    if issue_analysis:
        summary = issue_analysis.get("summary", "")
        # 把 summary 里超过 3 个字符的"词"加进去
        for word in summary.split():
            cleaned = word.strip(".,;:!?()'\"")
            if len(cleaned) >= 3:
                keywords.add(cleaned)

        # 从验收条件里也提取
        for criterion in issue_analysis.get("acceptance_criteria", []):
            for word in criterion.split():
                cleaned = word.strip(".,;:!?()'\"")
                if len(cleaned) >= 3:
                    keywords.add(cleaned)

    # ── 从 issue_text 里提取"代码风格"的词 ──
    # 代码标识符通常包含下划线、驼峰或数字
    import re
    # 匹配函数名、变量名、类名、方法名等模式
    code_identifiers = re.findall(
        r'\b[a-zA-Z][a-zA-Z0-9_]{2,}\b',
        issue_text,
    )
    for identifier in code_identifiers:
        # 过滤太通用的英文词（stop words）
        if identifier.lower() not in _STOP_WORDS:
            keywords.add(identifier)

    # 过滤太短的词（小于 3 个字符）
    filtered = [k for k in keywords if len(k) >= 3]

    # 按长度降序排，长词更具体更有搜索价值
    filtered.sort(key=len, reverse=True)

    logger.info(f"提取到 {len(filtered)} 个关键词：{filtered[:10]}")
    return filtered[:15]  # 最多返回 15 个关键词


# 英文停用词（太通用，搜索价值低）
_STOP_WORDS = {
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


def _collect_searchable_files(repo_path: Path) -> List[Path]:
    """
    递归收集仓库里所有可搜索的文件路径。

    参数:
        repo_path: 仓库根目录路径

    返回:
        符合条件的文件路径列表
    """
    files: List[Path] = []

    for root, dirs, filenames in os.walk(repo_path):
        # 就地修改 dirs，os.walk 就不会继续进入这些目录
        # 这是用 os.walk 过滤目录的标准做法
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]

        for filename in filenames:
            file_path = Path(root) / filename
            suffix = file_path.suffix.lower()

            if suffix not in SEARCHABLE_EXTENSIONS:
                continue

            # 跳过太大的文件
            try:
                if file_path.stat().st_size > MAX_FILE_SIZE_BYTES:
                    continue
            except OSError:
                continue

            files.append(file_path)

    return files


def _search_file_for_keywords(
    file_path: Path,
    repo_path: Path,
    keywords: List[str],
    max_snippet_lines: int,
) -> Tuple[float, RetrievedFile | None]:
    """
    在单个文件里搜索关键词，返回相关度评分和文件信息。

    搜索策略：
    1. 读取文件内容，按行存储
    2. 对每一行检查是否包含任意关键词
    3. 找出"命中行"，提取包含这些行的代码片段
    4. 评分 = 命中关键词数量 × 权重

    参数:
        file_path: 要搜索的文件路径
        repo_path: 仓库根目录（用于计算相对路径）
        keywords: 关键词列表
        max_snippet_lines: 每个文件最多返回多少行代码

    返回:
        (score, RetrievedFile | None)
        score=0 且 result=None 表示没有命中
    """
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
    except OSError as e:
        logger.warning(f"无法读取文件 {file_path}：{e}")
        return 0.0, None

    lines = content.splitlines()

    # 对每一行检查是否命中任意关键词
    # hit_lines: {行号: [命中的关键词列表]}
    hit_lines: dict[int, list[str]] = {}
    keywords_lower = [k.lower() for k in keywords]

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

    # ── 计算评分 ──
    # 命中的唯一关键词越多、命中行越多，评分越高
    all_matched_keywords = set()
    for matched in hit_lines.values():
        all_matched_keywords.update(matched)

    score = (
        len(all_matched_keywords) * 20.0  # 每个唯一关键词 +20 分
        + min(len(hit_lines), 5) * 5.0     # 每个命中行 +5 分，最多 5 行
    )

    # ── 提取最相关的代码片段 ──
    # 找到第一个命中行，提取它周围的上下文
    first_hit_line = min(hit_lines.keys())

    # 上下文：命中行前 5 行 + 命中行 + 命中行后 (max_snippet_lines - 5) 行
    context_before = 5
    snippet_start = max(0, first_hit_line - context_before)
    snippet_end = min(len(lines), snippet_start + max_snippet_lines)

    snippet_lines = lines[snippet_start:snippet_end]
    snippet = "\n".join(snippet_lines)

    # 计算相对路径（相对于仓库根目录，用于展示）
    try:
        relative_path = str(file_path.relative_to(repo_path))
        # Windows 路径分隔符统一成 /
        relative_path = relative_path.replace("\\", "/")
    except ValueError:
        relative_path = str(file_path)

    result = RetrievedFile(
        file_path=relative_path,
        line_start=snippet_start + 1,  # 转成 1-based 行号
        line_end=snippet_start + len(snippet_lines),
        snippet=snippet,
        matched_keywords=list(all_matched_keywords),
        score=score,
    )

    return score, result


def retrieve_code(request: CodeRetrievalRequest) -> CodeRetrievalResult:
    """
    在仓库里搜索与 issue 相关的代码文件。

    整体流程：
    1. 收集仓库里所有可搜索文件
    2. 对每个文件用关键词搜索
    3. 按相关度评分排序
    4. 返回 top-N 结果

    参数:
        request: CodeRetrievalRequest，包含 repo_path 和关键词列表

    返回:
        CodeRetrievalResult：检索到的文件列表

    异常:
        FileNotFoundError: 仓库路径不存在时
    """
    repo_path = Path(request.repo_path)

    if not repo_path.exists():
        raise FileNotFoundError(f"仓库路径不存在：{repo_path}")

    if not request.keywords:
        logger.warning("关键词列表为空，无法检索")
        return CodeRetrievalResult(
            retrieved_files=[],
            total_searched_files=0,
            keywords_used=[],
        )

    logger.info(
        f"开始代码检索：repo={repo_path.name}, "
        f"关键词数量={len(request.keywords)}, "
        f"关键词={request.keywords}"
    )

    # ── 第 1 步：收集可搜索文件 ──
    all_files = _collect_searchable_files(repo_path)
    logger.info(f"共找到 {len(all_files)} 个可搜索文件")

    # ── 第 2 步：对每个文件搜索关键词 ──
    scored_results: List[Tuple[float, RetrievedFile]] = []

    for file_path in all_files:
        score, result = _search_file_for_keywords(
            file_path=file_path,
            repo_path=repo_path,
            keywords=request.keywords,
            max_snippet_lines=request.max_snippet_lines,
        )
        if result is not None and score > 0:
            scored_results.append((score, result))

    # ── 第 3 步：按评分排序，取 top-N ──
    scored_results.sort(key=lambda x: x[0], reverse=True)
    top_results = [result for _, result in scored_results[: request.max_files]]

    logger.info(
        f"代码检索完成：命中文件数={len(scored_results)}，"
        f"返回 top-{len(top_results)} 个"
    )

    return CodeRetrievalResult(
        retrieved_files=top_results,
        total_searched_files=len(all_files),
        keywords_used=request.keywords,
        search_method="keyword",
    )

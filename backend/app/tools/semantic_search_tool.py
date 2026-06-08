# backend/app/tools/semantic_search_tool.py
#
# 作用：用 LlamaIndex 对代码仓库建立向量索引，并提供语义检索能力。
#
# 语义检索的核心思路：
# - 把代码文件按固定行数切分成 chunk（每块约 50 行）
# - 用 OpenAI text-embedding-3-small 把每个 chunk 向量化
# - 把所有向量存到 VectorStoreIndex（内存 + 磁盘缓存）
# - 查询时把 issue_text 向量化，找余弦相似度最高的 top-k chunk
#
# 语义检索 vs 关键词检索：
# - 关键词：只找包含特定字符串的代码，遗漏重命名的函数和同义词
# - 语义：找"含义相近"的代码，例如 issue 说 "validation fails"，
#         语义检索能找到叫 check_input / validate_data 的函数
#
# 为什么要缓存索引？
# - 向量化需要调用 Embedding API（有成本、有延迟）
# - 同一个 repo 只需要向量化一次
# - 后续查询直接加载缓存，速度快得多

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    # 只在类型检查时导入，运行时延迟导入，避免启动慢
    from llama_index.core import VectorStoreIndex

logger = logging.getLogger(__name__)

# ── 文件过滤配置 ──────────────────────────────────────────────────────────────

# 只对这些扩展名的文件建索引（跳过图片、字体、二进制等）
SEARCHABLE_EXTENSIONS: set[str] = {
    ".py", ".js", ".ts", ".tsx", ".jsx",
    ".go", ".java", ".rs", ".rb", ".php",
    ".c", ".cpp", ".h", ".hpp",
    ".cs", ".swift", ".kt",
    ".md", ".txt", ".yaml", ".yml", ".toml", ".cfg", ".ini",
    ".json", ".xml", ".html", ".css", ".scss",
    ".sh", ".bash", ".zsh", ".sql",
}

# 跳过这些目录（无关内容，浪费 token）
IGNORED_DIRS: set[str] = {
    ".git", ".svn", "node_modules", "vendor",
    ".venv", "venv", "env", "__pycache__",
    "dist", "build", "out", "target", ".next",
    ".tox", ".eggs", "htmlcov",
}

MAX_FILE_SIZE_BYTES = 512 * 1024  # 512 KB，超过则跳过

# 每个 chunk 的行数
# 50 行约等于一个中等函数的长度，既不太碎也不太大
CHUNK_LINES = 50


# ── 内部工具函数 ──────────────────────────────────────────────────────────────

def _collect_searchable_files(repo_path: Path) -> List[Path]:
    """
    递归收集仓库里所有可搜索的文件路径。

    参数:
        repo_path: 仓库根目录

    返回:
        符合条件的文件路径列表
    """
    files: List[Path] = []

    for root, dirs, filenames in os.walk(repo_path):
        # 就地修改 dirs，os.walk 就不会进入被过滤的目录
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]

        for filename in filenames:
            file_path = Path(root) / filename

            if file_path.suffix.lower() not in SEARCHABLE_EXTENSIONS:
                continue

            try:
                if file_path.stat().st_size > MAX_FILE_SIZE_BYTES:
                    continue
            except OSError:
                continue

            files.append(file_path)

    return files


def _split_file_into_chunks(
    file_path: Path,
    repo_path: Path,
    chunk_lines: int = CHUNK_LINES,
) -> List[dict]:
    """
    把一个代码文件按行数切分成若干 chunk。

    为什么要切分而不是整个文件作为一个 Document？
    - 整个文件可能几百行，向量化后信息太分散，检索精度差
    - 切成 50 行的块，每块更聚焦，检索到相关函数/方法的概率更高
    - 保留精确的行号，方便 Planner Agent 知道要修改哪里

    参数:
        file_path: 要切分的文件
        repo_path: 仓库根目录（用于计算相对路径）
        chunk_lines: 每个 chunk 的行数

    返回:
        [{"file_path": "src/main.py", "line_start": 1, "line_end": 50, "content": "..."}, ...]
    """
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
    except OSError as e:
        logger.warning(f"无法读取文件 {file_path}：{e}")
        return []

    lines = content.splitlines()
    if not lines:
        return []

    # 统一用正斜杠表示相对路径（Windows/Linux 通用）
    try:
        relative_path = str(file_path.relative_to(repo_path)).replace("\\", "/")
    except ValueError:
        relative_path = str(file_path)

    chunks = []
    for i in range(0, len(lines), chunk_lines):
        chunk_line_list = lines[i : i + chunk_lines]
        chunks.append({
            "file_path": relative_path,
            "line_start": i + 1,           # 转成 1-based 行号
            "line_end": i + len(chunk_line_list),
            "content": "\n".join(chunk_line_list),
        })

    return chunks


# ── 公开 API ──────────────────────────────────────────────────────────────────

def build_code_index(
    repo_path: Path,
    cache_dir: Optional[Path] = None,
) -> "VectorStoreIndex":
    """
    为代码仓库构建 LlamaIndex 向量索引（支持磁盘缓存）。

    流程：
    1. 检查 cache_dir 是否已有索引 → 有则直接加载
    2. 没有则扫描 repo_path 里所有代码文件
    3. 按行切分成 chunk，每个 chunk 变成一个 Document
    4. 调用 OpenAI Embedding API 向量化所有 chunk
    5. 构建 VectorStoreIndex，持久化到 cache_dir

    参数:
        repo_path: 仓库本地路径
        cache_dir: 索引缓存目录，默认为 repo_path/../.llamaindex_cache

    返回:
        可直接查询的 VectorStoreIndex 实例

    异常:
        ValueError: 仓库里没有可索引的文件
    """
    # 延迟导入：只在实际调用时加载 LlamaIndex，避免影响 FastAPI 启动速度
    from llama_index.core import (
        Document,
        Settings,
        StorageContext,
        VectorStoreIndex,
        load_index_from_storage,
    )
    from llama_index.embeddings.openai import OpenAIEmbedding

    from app.core.config import get_settings

    app_settings = get_settings()

    # 配置 Embedding 模型
    # text-embedding-3-small：便宜、快、1536 维，适合代码检索
    # api_base 指向用户配置的兼容端点（同时支持 OpenAI 和 DeepSeek 聚合服务）
    Settings.embed_model = OpenAIEmbedding(
        model="text-embedding-3-small",
        api_key=app_settings.openai_api_key,
        api_base=app_settings.openai_base_url,
    )
    # 只用于检索，不需要 LLM
    Settings.llm = None

    # 默认缓存目录：repo 同级的 .llamaindex_cache 文件夹
    if cache_dir is None:
        cache_dir = repo_path.parent / ".llamaindex_cache"

    # ── 尝试加载已有索引（跳过重复向量化）──
    docstore_file = cache_dir / "docstore.json"
    if docstore_file.exists():
        logger.info(f"发现已有索引缓存，直接加载：{cache_dir}")
        try:
            storage_context = StorageContext.from_defaults(
                persist_dir=str(cache_dir)
            )
            index = load_index_from_storage(storage_context)
            logger.info("语义索引加载成功")
            return index
        except Exception as e:
            logger.warning(f"加载已有索引失败，将重新构建：{e}")

    # ── 构建新索引 ──
    logger.info(f"开始构建语义索引：{repo_path.name}")

    all_files = _collect_searchable_files(repo_path)
    logger.info(f"共找到 {len(all_files)} 个可索引文件，开始切分 chunk...")

    documents: List[Document] = []
    for file_path in all_files:
        chunks = _split_file_into_chunks(file_path, repo_path)
        for chunk in chunks:
            # 把代码片段和元数据打包成 Document
            # excluded_embed_metadata_keys：行号和路径不加入向量，
            # 只有代码内容本身参与向量化，让相似度更纯粹地基于语义
            doc = Document(
                text=chunk["content"],
                metadata={
                    "file_path": chunk["file_path"],
                    "line_start": chunk["line_start"],
                    "line_end": chunk["line_end"],
                },
                excluded_embed_metadata_keys=[
                    "line_start", "line_end", "file_path"
                ],
                excluded_llm_metadata_keys=["line_start", "line_end"],
            )
            documents.append(doc)

    if not documents:
        raise ValueError(
            f"仓库 {repo_path} 中没有找到可索引的代码文件，"
            "请检查仓库是否已正确 clone。"
        )

    logger.info(
        f"共 {len(documents)} 个 chunk，开始向量化（正在调用 Embedding API...）"
    )

    # show_progress=True 在终端显示向量化进度条，方便观察大型仓库的处理进度
    index = VectorStoreIndex.from_documents(documents, show_progress=True)

    # 持久化索引到磁盘，下次加载无需重新向量化
    cache_dir.mkdir(parents=True, exist_ok=True)
    index.storage_context.persist(persist_dir=str(cache_dir))
    logger.info(f"语义索引已缓存到：{cache_dir}")

    return index


def semantic_search(
    index: "VectorStoreIndex",
    query_text: str,
    top_k: int = 10,
) -> List[dict]:
    """
    用 issue 文本查询语义索引，返回最相关的代码 chunk。

    工作原理：
    1. 把 query_text（issue 描述）向量化
    2. 在索引里找余弦相似度最高的 top_k 个 chunk
    3. 返回带有 file_path/line_start/line_end/snippet/score 的列表

    参数:
        index: build_code_index() 返回的 VectorStoreIndex
        query_text: 查询文本，通常是 issue_text 或 issue 摘要
        top_k: 返回最相关的 top_k 个结果

    返回:
        [
            {
                "file_path": "src/utils/validator.py",
                "line_start": 10,
                "line_end": 60,
                "snippet": "def validate_input(...)...",
                "score": 0.87
            },
            ...
        ]
    """
    # as_retriever() 创建一个检索器，similarity_top_k 控制返回数量
    retriever = index.as_retriever(similarity_top_k=top_k)

    # retrieve() 内部：向量化 query → 计算相似度 → 返回 top-k 节点
    nodes = retriever.retrieve(query_text)

    results = []
    for node in nodes:
        metadata = node.node.metadata
        results.append({
            "file_path": metadata.get("file_path", "unknown"),
            "line_start": metadata.get("line_start", 1),
            "line_end": metadata.get("line_end", 1),
            "snippet": node.node.get_content(),
            # score 是余弦相似度（0~1），越高越相关
            "score": round(float(node.score or 0.0), 4),
        })

    return results

# backend/app/tools/read_file_tool.py
# 作用：读取 workspace 内仓库文件（FR-304）
#
# 安全：路径必须在 repo_path 内，禁止 ../ 逃逸
# 大小：单次默认最多 30KB，超出需分段读取

import logging
from pathlib import Path

from app.tools.path_utils import resolve_repo_file

logger = logging.getLogger(__name__)

MAX_READ_BYTES = 30 * 1024  # 30KB，对齐需求文档 FR-304


def read_file(
    repo_path: str,
    file_path: str,
    offset: int = 0,
    max_bytes: int = MAX_READ_BYTES,
) -> dict:
    """
    读取仓库内单个文件内容。

    返回:
        {
            "file_path": str,
            "content": str,
            "total_bytes": int,
            "offset": int,
            "truncated": bool,
            "error": str | None,
        }
    """
    try:
        resolved = resolve_repo_file(repo_path, file_path)
    except PermissionError as exc:
        logger.warning(f"读取文件被拒绝：{exc}")
        return {
            "file_path": file_path,
            "content": "",
            "total_bytes": 0,
            "offset": offset,
            "truncated": False,
            "error": str(exc),
        }

    if not resolved.exists():
        return {
            "file_path": file_path,
            "content": "",
            "total_bytes": 0,
            "offset": offset,
            "truncated": False,
            "error": f"文件不存在：{file_path}",
        }

    if not resolved.is_file():
        return {
            "file_path": file_path,
            "content": "",
            "total_bytes": 0,
            "offset": offset,
            "truncated": False,
            "error": f"不是文件：{file_path}",
        }

    raw = resolved.read_bytes()
    total_bytes = len(raw)

    if offset < 0:
        offset = 0
    if offset > total_bytes:
        offset = total_bytes

    chunk = raw[offset : offset + max_bytes]
    truncated = (offset + len(chunk)) < total_bytes

    try:
        content = chunk.decode("utf-8")
    except UnicodeDecodeError:
        return {
            "file_path": file_path,
            "content": "",
            "total_bytes": total_bytes,
            "offset": offset,
            "truncated": False,
            "error": f"文件不是 UTF-8 文本：{file_path}",
        }

    logger.info(
        f"读取文件：{file_path} offset={offset} "
        f"bytes={len(chunk)}/{total_bytes} truncated={truncated}"
    )

    return {
        "file_path": file_path,
        "content": content,
        "total_bytes": total_bytes,
        "offset": offset,
        "truncated": truncated,
        "error": None,
    }

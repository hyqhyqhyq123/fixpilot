# backend/app/tools/edit_file_tool.py
# 作用：在允许列表内写入文件，保存快照并生成 diff（FR-502）

import difflib
import logging
from pathlib import Path

from app.tools.path_utils import resolve_repo_file

logger = logging.getLogger(__name__)


def _normalize_allowed(path: str) -> str:
    """统一路径分隔符，便于白名单比对。"""
    return path.replace("\\", "/")


def edit_file(
    repo_path: str,
    file_path: str,
    new_content: str,
    allowed_files: list[str],
    is_new_file: bool = False,
) -> dict:
    """
    写入文件并返回修改快照。

    返回:
        {
            "success": bool,
            "file_path": str,
            "before_content": str | None,
            "after_content": str | None,
            "diff": str | None,
            "error": str | None,
        }
    """
    normalized = _normalize_allowed(file_path)
    allowed_set = {_normalize_allowed(p) for p in allowed_files}

    if normalized not in allowed_set:
        return {
            "success": False,
            "file_path": file_path,
            "before_content": None,
            "after_content": None,
            "diff": None,
            "error": f"文件不在允许修改列表中：{file_path}",
        }

    try:
        resolved = resolve_repo_file(repo_path, file_path)
    except PermissionError as exc:
        return {
            "success": False,
            "file_path": file_path,
            "before_content": None,
            "after_content": None,
            "diff": None,
            "error": str(exc),
        }

    if resolved.exists() and not resolved.is_file():
        return {
            "success": False,
            "file_path": file_path,
            "before_content": None,
            "after_content": None,
            "diff": None,
            "error": f"目标不是文件：{file_path}",
        }

    if not is_new_file and not resolved.exists():
        return {
            "success": False,
            "file_path": file_path,
            "before_content": None,
            "after_content": None,
            "diff": None,
            "error": f"要修改的文件不存在：{file_path}",
        }

    if is_new_file and resolved.exists():
        return {
            "success": False,
            "file_path": file_path,
            "before_content": None,
            "after_content": None,
            "diff": None,
            "error": f"新建文件已存在：{file_path}",
        }

    before_content: str | None = None
    if resolved.exists():
        try:
            before_content = resolved.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return {
                "success": False,
                "file_path": file_path,
                "before_content": None,
                "after_content": None,
                "diff": None,
                "error": f"无法读取原文件（非 UTF-8）：{file_path}",
            }

    # 写入前创建父目录（新建文件场景）
    resolved.parent.mkdir(parents=True, exist_ok=True)

    try:
        resolved.write_text(new_content, encoding="utf-8")
    except OSError as exc:
        return {
            "success": False,
            "file_path": file_path,
            "before_content": before_content,
            "after_content": None,
            "diff": None,
            "error": f"写入失败：{exc}",
        }

    after_content = new_content
    before_lines = (before_content or "").splitlines(keepends=True)
    after_lines = after_content.splitlines(keepends=True)
    diff = "".join(
        difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}",
        )
    )

    logger.info(f"文件已修改：{file_path} diff_lines={len(diff.splitlines())}")
    return {
        "success": True,
        "file_path": file_path,
        "before_content": before_content,
        "after_content": after_content,
        "diff": diff or f"--- a/{file_path}\n+++ b/{file_path}\n（新文件）\n",
        "error": None,
    }


def rollback_file(repo_path: str, file_path: str, before_content: str | None) -> None:
    """应用失败时回滚：有快照则恢复，新建文件则删除。"""
    resolved = resolve_repo_file(repo_path, file_path)
    if before_content is None:
        if resolved.exists():
            resolved.unlink()
            logger.info(f"已删除新建文件（回滚）：{file_path}")
    else:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(before_content, encoding="utf-8")
        logger.info(f"已回滚文件：{file_path}")

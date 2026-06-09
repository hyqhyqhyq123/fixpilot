# backend/app/tools/path_utils.py
# 作用：校验仓库内文件路径，防止路径逃逸（FR-304 / FR-502 安全要求）

from pathlib import Path


def resolve_repo_file(repo_path: str, file_path: str) -> Path:
    """
    把「相对仓库根目录的路径」解析为安全绝对路径。

    参数:
        repo_path: 仓库根目录（clone 后的路径）
        file_path: 相对路径，如 app/main.py

    异常:
        PermissionError: 路径试图逃出 repo 根目录时
    """
    root = Path(repo_path).resolve()
    resolved = (root / file_path).resolve()

    # 必须仍在 repo 根目录下（含相等）
    if root != resolved and root not in resolved.parents:
        raise PermissionError(
            f"路径逃逸：{file_path} 解析为 {resolved}，不在仓库 {root} 内"
        )
    return resolved

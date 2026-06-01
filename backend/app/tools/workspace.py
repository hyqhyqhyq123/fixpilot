# backend/app/tools/workspace.py
# 作用：管理每个任务的独立工作目录（Workspace）
#
# Workspace 是什么？
# 每个修复任务需要一个独立的文件夹来存放 clone 下来的代码。
# 比如任务 ID=1 的 workspace 路径是：workspaces/task_1/
# Agent 只能在这个目录里读写文件，不能访问外部，保证安全。

import logging
import shutil
from pathlib import Path

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def get_workspace_base() -> Path:
    """
    获取 workspace 根目录的绝对路径。

    .env 里配置的 WORKSPACE_BASE_PATH 可能是相对路径（如 ../workspaces），
    需要转成绝对路径才能安全使用。resolve() 会解析 .. 并返回绝对路径。
    """
    settings = get_settings()
    base = Path(settings.workspace_base_path).resolve()
    return base


def create_workspace(task_id: int) -> Path:
    """
    为指定任务创建独立 workspace 目录。

    参数:
        task_id: 任务 ID，用于生成唯一目录名

    返回:
        workspace 目录的绝对路径

    为什么每个任务要独立 workspace？
    - 多个任务可能处理同一个仓库，文件修改会冲突
    - 独立目录让每个任务都有干净的代码副本
    - 后续 Docker 测试也会基于这个目录运行
    """
    workspace_path = get_workspace_base() / f"task_{task_id}"
    workspace_path.mkdir(parents=True, exist_ok=True)

    logger.info(f"Workspace 已创建：{workspace_path}")
    return workspace_path


def get_workspace_path(task_id: int) -> Path:
    """
    获取指定任务的 workspace 路径（不创建目录）。

    参数:
        task_id: 任务 ID

    返回:
        workspace 目录路径

    异常:
        FileNotFoundError: workspace 目录不存在时抛出
    """
    workspace_path = get_workspace_base() / f"task_{task_id}"

    if not workspace_path.exists():
        raise FileNotFoundError(
            f"任务 {task_id} 的 workspace 不存在：{workspace_path}。"
            f"请先调用 create_workspace({task_id}) 创建。"
        )

    return workspace_path


def cleanup_workspace(task_id: int) -> None:
    """
    清理指定任务的 workspace（删除整个目录）。

    什么时候调用？
    - 任务完成或取消后，清理磁盘空间
    - 注意：生产环境可能要先归档再删除，MVP 先直接删

    安全检查：只删除 workspace 根目录下的子目录，防止误删其他文件。
    """
    workspace_path = get_workspace_base() / f"task_{task_id}"

    if not workspace_path.exists():
        logger.warning(f"Workspace 不存在，跳过清理：{workspace_path}")
        return

    # 安全检查：确保要删除的目录确实在 workspace 根目录下
    if not _is_safe_path(workspace_path):
        logger.error(f"路径安全检查失败，拒绝删除：{workspace_path}")
        raise PermissionError(f"拒绝删除不安全的路径：{workspace_path}")

    shutil.rmtree(workspace_path)
    logger.info(f"Workspace 已清理：{workspace_path}")


def validate_path_in_workspace(task_id: int, target_path: str) -> Path:
    """
    验证目标路径是否在 workspace 范围内，防止路径逃逸攻击。

    什么是路径逃逸？
    如果 Agent 传入 "../../etc/passwd"，resolve 后会指向系统文件。
    这个函数确保所有路径都在 workspace_base/task_X/ 下面。

    参数:
        task_id: 任务 ID
        target_path: Agent 想要访问的路径（可能包含 .. 等危险字符）

    返回:
        验证通过的安全绝对路径

    异常:
        PermissionError: 路径逃逸时抛出
    """
    workspace = get_workspace_path(task_id)
    # resolve() 会解析 .. 和符号链接，得到真正的绝对路径
    resolved = (workspace / target_path).resolve()

    # 检查 resolved 是否仍在 workspace 目录下
    if not str(resolved).startswith(str(workspace)):
        logger.error(
            f"路径逃逸检测！task_id={task_id}, "
            f"target_path={target_path}, resolved={resolved}"
        )
        raise PermissionError(
            f"路径逃逸：{target_path} 指向了 workspace 外部，已拒绝访问。"
        )

    return resolved


def _is_safe_path(path: Path) -> bool:
    """
    检查路径是否在 workspace 根目录下（内部辅助函数）。

    _ 开头表示这是私有函数，只在本模块内使用。
    """
    workspace_base = get_workspace_base()
    resolved = path.resolve()
    return str(resolved).startswith(str(workspace_base))

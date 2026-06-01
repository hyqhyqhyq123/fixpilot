# backend/app/tools/repo_clone_tool.py
# 作用：将 GitHub 公开仓库 clone 到任务的 workspace 目录
#
# 为什么改用 subprocess？
# GitPython 的 kill_after_timeout 参数底层使用 Unix 信号（SIGKILL），
# 在 Windows 上不支持。改用 subprocess.run() + timeout 参数，
# 这是 Python 标准库跨平台实现超时的方式。

import logging
import re
import subprocess
from pathlib import Path

from app.tools.workspace import create_workspace, get_workspace_path

logger = logging.getLogger(__name__)

# clone 超时时间（秒）：防止超大仓库或网络问题卡住整个系统
CLONE_TIMEOUT_SECONDS = 300

# 限制 clone 深度：只拿最近 1 次 commit，加快速度、节省磁盘
# 因为 FixPilot 只需要最新代码来分析和修改，不需要完整历史
DEFAULT_CLONE_DEPTH = 1


def validate_repo_url(repo_url: str) -> bool:
    """
    验证 GitHub 仓库 URL 格式是否合法。

    只允许 https://github.com/owner/repo 格式，
    不支持 SSH（git@github.com:...）和其他平台（暂时只支持 GitHub）。

    为什么要验证？
    - 防止用户传入恶意 URL（比如 file:///etc/passwd）
    - 确保只 clone GitHub 公开仓库
    """
    pattern = r"^https://github\.com/[\w\-\.]+/[\w\-\.]+/?$"
    return bool(re.match(pattern, repo_url))


def clone_repo(task_id: int, repo_url: str) -> dict:
    """
    克隆 GitHub 仓库到任务的 workspace 目录。

    参数:
        task_id: 任务 ID，用于定位 workspace
        repo_url: GitHub 仓库地址（https://github.com/owner/repo）

    返回:
        dict: 包含 clone 结果信息
            - success: 是否成功
            - workspace_path: workspace 目录路径
            - repo_path: 仓库在 workspace 中的路径
            - message: 结果描述
            - error: 错误信息（仅失败时）

    工作流程:
        1. 验证 URL 格式
        2. 创建 workspace 目录
        3. 从 URL 中提取仓库名
        4. 执行 git clone（浅克隆，只取最新代码）
        5. 返回结果
    """
    # ── 第 1 步：验证 URL ──
    if not validate_repo_url(repo_url):
        logger.warning(f"无效的仓库 URL：{repo_url}")
        return {
            "success": False,
            "workspace_path": None,
            "repo_path": None,
            "message": "仓库 URL 格式无效",
            "error": (
                f"不支持的 URL 格式：{repo_url}。"
                "请使用 https://github.com/owner/repo 格式。"
            ),
        }

    # ── 第 2 步：创建 workspace ──
    workspace_path = create_workspace(task_id)

    # ── 第 3 步：从 URL 提取仓库名 ──
    # "https://github.com/pallets/flask/" → "flask"
    repo_name = repo_url.rstrip("/").split("/")[-1]
    # 去掉 .git 后缀（如果有的话）
    if repo_name.endswith(".git"):
        repo_name = repo_name[:-4]

    repo_path = workspace_path / repo_name

    # ── 第 4 步：检查是否已经 clone 过 ──
    if repo_path.exists():
        logger.info(f"仓库目录已存在，跳过 clone：{repo_path}")
        return {
            "success": True,
            "workspace_path": str(workspace_path),
            "repo_path": str(repo_path),
            "message": f"仓库已存在于 {repo_path}，跳过 clone",
            "error": None,
        }

    # ── 第 5 步：执行 git clone ──
    try:
        logger.info(
            f"开始 clone：{repo_url} → {repo_path} "
            f"(depth={DEFAULT_CLONE_DEPTH}, timeout={CLONE_TIMEOUT_SECONDS}s)"
        )

        # 构造 git clone 命令参数列表
        # 等价于：git clone --depth=1 --single-branch <url> <path>
        cmd = [
            "git", "clone",
            f"--depth={DEFAULT_CLONE_DEPTH}",
            "--single-branch",
            repo_url,
            str(repo_path),
        ]

        # subprocess.run() 是 Python 标准库调用外部命令的方式
        # timeout 参数在 Windows/Linux/Mac 均可用，超时后抛出 TimeoutExpired
        # capture_output=True 捕获 stdout 和 stderr，避免输出到控制台
        # text=True 将输出解码为字符串（而非 bytes）
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=CLONE_TIMEOUT_SECONDS,
        )

        # git clone 成功时 returncode 为 0
        if result.returncode != 0:
            error_msg = result.stderr.strip() or result.stdout.strip()
            logger.error(f"Clone 失败（exit code {result.returncode}）：{error_msg}")
            return {
                "success": False,
                "workspace_path": str(workspace_path),
                "repo_path": None,
                "message": "Git clone 失败",
                "error": error_msg,
            }

        logger.info(f"Clone 成功：{repo_path}")

        return {
            "success": True,
            "workspace_path": str(workspace_path),
            "repo_path": str(repo_path),
            "message": f"仓库已成功 clone 到 {repo_path}",
            "error": None,
        }

    except subprocess.TimeoutExpired:
        # clone 超时后，subprocess 会留下一个不完整的目录，需要清理
        logger.error(f"Clone 超时（>{CLONE_TIMEOUT_SECONDS}s）：{repo_url}")
        _cleanup_incomplete_repo(repo_path)
        return {
            "success": False,
            "workspace_path": str(workspace_path),
            "repo_path": None,
            "message": f"Git clone 超时（超过 {CLONE_TIMEOUT_SECONDS} 秒）",
            "error": "clone 超时，仓库可能过大或网络不稳定",
        }

    except FileNotFoundError:
        # 系统找不到 git 命令时报这个错
        logger.error("未找到 git 命令，请确认 Git 已安装并加入 PATH")
        return {
            "success": False,
            "workspace_path": str(workspace_path),
            "repo_path": None,
            "message": "系统未找到 git 命令",
            "error": "请安装 Git 并确保 git 在 PATH 中",
        }

    except Exception as e:
        logger.error(f"Clone 过程中出现意外错误：{e}")
        return {
            "success": False,
            "workspace_path": str(workspace_path),
            "repo_path": None,
            "message": "Clone 过程中出现意外错误",
            "error": str(e),
        }


def _cleanup_incomplete_repo(repo_path: Path) -> None:
    """
    清理 clone 超时后残留的不完整目录。

    为什么需要清理？
    - clone 超时时 git 已创建了目录但内容不完整
    - 下次重试时，代码会检测到目录存在就跳过 clone，导致使用损坏的仓库
    """
    import shutil
    if repo_path.exists():
        try:
            shutil.rmtree(repo_path)
            logger.info(f"已清理不完整的仓库目录：{repo_path}")
        except Exception as e:
            logger.warning(f"清理失败：{repo_path}，原因：{e}")

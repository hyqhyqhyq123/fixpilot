# backend/app/tools/git_diff_tool.py
# 作用：获取仓库当前 git diff（FR-502 要求修改后生成 diff）

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def get_git_diff(repo_path: str) -> dict:
    """
    在仓库目录执行 git diff，返回工作区相对 HEAD 的差异。

    返回:
        {"success": bool, "diff": str, "error": str | None}
    """
    root = Path(repo_path).resolve()
    if not (root / ".git").exists():
        return {
            "success": False,
            "diff": "",
            "error": f"目录不是 git 仓库：{repo_path}",
        }

    try:
        result = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode not in (0, 1):
            # git diff 有差异时也可能返回 1，视版本而定；0 和 1 通常都可接受
            err = result.stderr.strip() or result.stdout.strip()
            return {"success": False, "diff": "", "error": err}

        diff_text = result.stdout
        logger.info(f"git diff 完成：{root.name}，长度={len(diff_text)}")
        return {"success": True, "diff": diff_text, "error": None}

    except subprocess.TimeoutExpired:
        return {"success": False, "diff": "", "error": "git diff 超时"}
    except FileNotFoundError:
        return {"success": False, "diff": "", "error": "未找到 git 命令"}
    except Exception as exc:
        logger.error(f"git diff 失败：{exc}")
        return {"success": False, "diff": "", "error": str(exc)}

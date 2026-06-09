# backend/app/tools/run_tests_tool.py
# 作用：在 Docker 沙箱中执行测试命令（FR-601 / FR-604）
#
# 为什么用 Docker？
# 测试命令不可信，必须在隔离环境跑，限制 CPU/内存/超时。

import logging
import subprocess
import time
from pathlib import Path

from app.schemas.test_result import TestRunResult

logger = logging.getLogger(__name__)

DOCKER_MEMORY = "2g"
DOCKER_CPUS = "2"
DOCKER_TIMEOUT_SECONDS = 120


def _pick_docker_image(project_type: str | None) -> str:
    """根据项目类型选择基础镜像。"""
    mapping = {
        "python": "python:3.11-slim",
        "nodejs": "node:20-slim",
        "go": "golang:1.22-alpine",
        "rust": "rust:1.77-slim",
    }
    if project_type and project_type in mapping:
        return mapping[project_type]
    return "python:3.11-slim"


def run_tests_in_docker(
    repo_path: str,
    command: str,
    project_type: str | None = None,
    timeout_seconds: int = DOCKER_TIMEOUT_SECONDS,
) -> TestRunResult:
    """
    在 Docker 容器里执行测试命令。

    挂载仓库到 /workspace，禁用网络，限制资源。
    """
    repo_abs = str(Path(repo_path).resolve())
    image = _pick_docker_image(project_type)

    # Windows 路径需传给 Docker Desktop；使用绝对路径
    docker_cmd = [
        "docker", "run", "--rm",
        "-v", f"{repo_abs}:/workspace",
        "-w", "/workspace",
        "--memory", DOCKER_MEMORY,
        "--cpus", DOCKER_CPUS,
        "--network", "none",
        image,
        "sh", "-c", command,
    ]

    logger.info(f"Docker 测试开始：image={image}, cmd={command}")
    started = time.perf_counter()

    try:
        result = subprocess.run(
            docker_cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        passed = result.returncode == 0

        return TestRunResult(
            command=command,
            exit_code=result.returncode,
            stdout=result.stdout or "",
            stderr=result.stderr or "",
            duration_ms=duration_ms,
            passed=passed,
            timed_out=False,
            error_message=None if passed else f"测试失败，exit_code={result.returncode}",
        )

    except subprocess.TimeoutExpired as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        stdout = exc.stdout.decode("utf-8", errors="replace") if exc.stdout else ""
        stderr = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else ""
        return TestRunResult(
            command=command,
            exit_code=-1,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
            passed=False,
            timed_out=True,
            error_message=f"测试超时（>{timeout_seconds}s）",
        )

    except FileNotFoundError:
        return TestRunResult(
            command=command,
            exit_code=-1,
            stdout="",
            stderr="",
            duration_ms=0,
            passed=False,
            timed_out=False,
            error_message="未找到 docker 命令，请确认 Docker 已安装并在 PATH 中",
        )

    except Exception as exc:
        logger.error(f"Docker 测试异常：{exc}")
        return TestRunResult(
            command=command,
            exit_code=-1,
            stdout="",
            stderr="",
            duration_ms=0,
            passed=False,
            timed_out=False,
            error_message=str(exc),
        )

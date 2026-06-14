"""集中管理 FixTask 的状态门禁。

为什么要单独放这里：
任务状态如果散落在 API、Celery、Workflow 里分别判断，面试时很难说明
“哪些状态能做哪些动作”。这个文件把核心规则收拢成小函数，其他模块只负责调用。
"""

from __future__ import annotations

from app.models.fix_task import TaskStatus


STARTABLE_STATUSES = {TaskStatus.PENDING, TaskStatus.FAILED}
WAITING_CONTINUABLE_STATUSES = {TaskStatus.WAITING_APPROVAL}
RETRYABLE_STATUSES = {TaskStatus.FAILED}
CANCELLABLE_STATUSES = {
    TaskStatus.PENDING,
    TaskStatus.WAITING_APPROVAL,
    TaskStatus.RUNNING,
}

# 这是面向解释和测试的状态图，不直接替代 workflow 的每一次写库。
# 例如 success -> failed 是“回滚到某次 retry”场景需要的人工恢复路径。
ALLOWED_STATUS_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {TaskStatus.RUNNING, TaskStatus.CANCELLED},
    TaskStatus.RUNNING: {
        TaskStatus.WAITING_APPROVAL,
        TaskStatus.SUCCESS,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.WAITING_APPROVAL: {
        TaskStatus.RUNNING,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.FAILED: {TaskStatus.RUNNING},
    TaskStatus.SUCCESS: {TaskStatus.FAILED},
    TaskStatus.CANCELLED: set(),
}


def normalize_status(status: TaskStatus | str) -> TaskStatus:
    """把字符串或枚举统一转成 TaskStatus，避免调用方到处写转换代码。"""
    if isinstance(status, TaskStatus):
        return status
    return TaskStatus(status)


def can_transition(current: TaskStatus | str, target: TaskStatus | str) -> bool:
    """判断一个状态流转是否在状态图里被允许。"""
    current_status = normalize_status(current)
    target_status = normalize_status(target)
    return target_status in ALLOWED_STATUS_TRANSITIONS[current_status]


def require_transition(current: TaskStatus | str, target: TaskStatus | str) -> None:
    """不允许的状态流转直接抛错，让调用方返回 400 或记录失败原因。"""
    if not can_transition(current, target):
        current_status = normalize_status(current)
        target_status = normalize_status(target)
        raise ValueError(
            f"非法任务状态流转：{current_status.value} -> {target_status.value}"
        )


def validate_start_status(status: TaskStatus | str, *, allow_running: bool = False) -> None:
    """校验任务是否可以启动。

    allow_running 用于 Celery worker 场景：API 已经先把任务标为 running，
    worker 取到任务后继续执行，不应被误判为重复启动。
    """
    current = normalize_status(status)
    allowed = set(STARTABLE_STATUSES)
    if allow_running:
        allowed.add(TaskStatus.RUNNING)
    if current not in allowed:
        allowed_text = "pending / failed / running" if allow_running else "pending / failed"
        raise ValueError(f"任务状态为 {current.value}，仅 {allowed_text} 可启动")


def validate_waiting_to_running(status: TaskStatus | str) -> None:
    """校验审批后的继续执行入口。"""
    current = normalize_status(status)
    if current not in WAITING_CONTINUABLE_STATUSES:
        raise ValueError("仅 waiting_approval 状态可继续执行")


def validate_retry_status(
    status: TaskStatus | str,
    retry_count: int,
    max_retries: int,
    *,
    allow_running: bool = False,
) -> None:
    """校验失败任务是否还能重试。"""
    current = normalize_status(status)
    if allow_running and current == TaskStatus.RUNNING:
        return
    if current not in RETRYABLE_STATUSES:
        raise ValueError("仅 failed 状态的任务可重试")
    if retry_count >= max_retries:
        raise ValueError(f"已达到最大重试次数（{max_retries}）")


def validate_cancel_status(status: TaskStatus | str) -> None:
    """校验任务是否允许取消。"""
    current = normalize_status(status)
    if current not in CANCELLABLE_STATUSES:
        raise ValueError(f"任务状态为 {current.value}，无法取消")

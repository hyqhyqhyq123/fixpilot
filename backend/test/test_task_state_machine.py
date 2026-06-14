import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.models.fix_task import TaskStatus
from app.services.task_state_machine import (
    can_transition,
    require_transition,
    validate_cancel_status,
    validate_retry_status,
    validate_start_status,
    validate_waiting_to_running,
)


def test_known_workflow_transitions_are_allowed():
    assert can_transition(TaskStatus.PENDING, TaskStatus.RUNNING)
    assert can_transition(TaskStatus.RUNNING, TaskStatus.WAITING_APPROVAL)
    assert can_transition(TaskStatus.WAITING_APPROVAL, TaskStatus.RUNNING)
    assert can_transition(TaskStatus.RUNNING, TaskStatus.SUCCESS)
    assert can_transition(TaskStatus.RUNNING, TaskStatus.FAILED)
    assert can_transition(TaskStatus.FAILED, TaskStatus.RUNNING)
    print("[OK] 状态机允许主流程、审批继续和失败重试路径")


def test_invalid_terminal_transition_is_rejected():
    try:
        require_transition(TaskStatus.CANCELLED, TaskStatus.RUNNING)
    except ValueError as exc:
        assert "cancelled -> running" in str(exc)
    else:
        raise AssertionError("cancelled 任务不应重新进入 running")
    print("[OK] cancelled 任务不能非法恢复为 running")


def test_start_status_guard_rejects_waiting_approval():
    validate_start_status(TaskStatus.PENDING)
    validate_start_status(TaskStatus.FAILED)

    try:
        validate_start_status(TaskStatus.WAITING_APPROVAL)
    except ValueError as exc:
        assert "仅 pending / failed 可启动" in str(exc)
    else:
        raise AssertionError("waiting_approval 不应走 start 入口")
    print("[OK] start 门禁拒绝 waiting_approval 重复启动")


def test_start_status_guard_allows_worker_running_resume():
    validate_start_status(TaskStatus.RUNNING, allow_running=True)
    print("[OK] Celery worker 场景允许 running 任务继续执行")


def test_waiting_to_running_guard_only_accepts_waiting_approval():
    validate_waiting_to_running(TaskStatus.WAITING_APPROVAL)

    try:
        validate_waiting_to_running(TaskStatus.PENDING)
    except ValueError as exc:
        assert "仅 waiting_approval 状态可继续执行" in str(exc)
    else:
        raise AssertionError("pending 任务不应走审批继续入口")
    print("[OK] 审批继续门禁只接受 waiting_approval")


def test_retry_guard_checks_failed_status_and_retry_limit():
    validate_retry_status(TaskStatus.FAILED, retry_count=1, max_retries=2)

    try:
        validate_retry_status(TaskStatus.RUNNING, retry_count=0, max_retries=2)
    except ValueError as exc:
        assert "仅 failed 状态的任务可重试" in str(exc)
    else:
        raise AssertionError("running 任务不应走普通 retry 入口")

    try:
        validate_retry_status(TaskStatus.FAILED, retry_count=2, max_retries=2)
    except ValueError as exc:
        assert "已达到最大重试次数" in str(exc)
    else:
        raise AssertionError("达到最大重试次数后不应继续 retry")
    print("[OK] retry 门禁校验 failed 状态和最大重试次数")


def test_cancel_guard_matches_workflow_cancel_policy():
    validate_cancel_status(TaskStatus.PENDING)
    validate_cancel_status(TaskStatus.WAITING_APPROVAL)
    validate_cancel_status(TaskStatus.RUNNING)

    try:
        validate_cancel_status(TaskStatus.SUCCESS)
    except ValueError as exc:
        assert "无法取消" in str(exc)
    else:
        raise AssertionError("success 任务不应被取消")
    print("[OK] Workflow cancel 门禁允许运行中取消，但拒绝已成功任务")

# backend/app/celery_app.py
# Celery 应用实例：用 Redis 作为 broker，在 Worker 中执行 Workflow 后台任务

import asyncio
import logging

from celery import Celery
from celery.signals import worker_process_init

from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

celery_app = Celery(
    "fixpilot",
    broker=settings.resolved_celery_broker_url,
    backend=settings.resolved_celery_result_backend,
    include=["app.tasks.workflow_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,
    worker_prefetch_multiplier=1,
)

if settings.celery_task_always_eager:
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True


@worker_process_init.connect
def _on_worker_process_init(**_kwargs) -> None:
    """Fork 后丢弃父进程继承的 async 连接池，并清空 Worker event loop 缓存。"""
    from app.db.session import engine
    from app.tasks.workflow_tasks import reset_worker_event_loop

    reset_worker_event_loop()
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(engine.dispose())
    except Exception as exc:
        logger.warning("Worker 进程初始化 dispose engine 失败: %s", exc)
    finally:
        loop.close()

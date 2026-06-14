# backend/test/test_db_indexes.py
# 面试向量化实验：检查高频查询路径是否有复合索引。
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.models.agent_step import AgentStep
from app.models.fix_task import FixTask
from app.models.retrieved_context import RetrievedContext
from app.models.task_status_transition import TaskStatusTransition
from app.models.tool_call import ToolCall


def _index_columns(model, index_name: str) -> tuple[str, ...]:
    for index in model.__table__.indexes:
        if index.name == index_name:
            return tuple(column.name for column in index.columns)
    raise AssertionError(f"{model.__tablename__} 缺少索引 {index_name}")


def test_high_frequency_query_indexes_are_declared():
    assert _index_columns(FixTask, "ix_fix_tasks_status_created_at") == (
        "status",
        "created_at",
    )
    assert _index_columns(FixTask, "ix_fix_tasks_created_at") == ("created_at",)
    assert _index_columns(AgentStep, "ix_agent_steps_task_started") == (
        "task_id",
        "started_at",
    )
    assert _index_columns(ToolCall, "ix_tool_calls_task_created") == (
        "task_id",
        "created_at",
    )
    assert _index_columns(
        RetrievedContext,
        "ix_retrieved_contexts_task_score_id",
    ) == ("task_id", "score", "id")
    assert _index_columns(
        TaskStatusTransition,
        "ix_task_status_transitions_task_created",
    ) == ("task_id", "created_at")
    print("[OK] 高频任务列表 / Trace / 工具审计 / 检索结果 / 状态审计均声明复合索引")


if __name__ == "__main__":
    test_high_frequency_query_indexes_are_declared()

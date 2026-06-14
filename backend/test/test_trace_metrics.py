# backend/test/test_trace_metrics.py
# Agent Trace 指标：latency_ms / token_usage / related_files
# 运行：cd backend && python test/test_trace_metrics.py

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.llm_trace import extract_token_usage, pop_token_usage, record_token_usage
from app.schemas.workflow import AgentStepResponse
from app.models.agent_step import StepStatus


def test_extract_token_usage_usage_metadata() -> None:
    response = SimpleNamespace(
        usage_metadata={
            "input_tokens": 120,
            "output_tokens": 45,
            "total_tokens": 165,
        },
        response_metadata={},
    )
    usage = extract_token_usage(response)
    assert usage == {
        "prompt_tokens": 120,
        "completion_tokens": 45,
        "total_tokens": 165,
    }
    print("[OK] extract_token_usage usage_metadata")


def test_record_and_pop_token_usage() -> None:
    response = SimpleNamespace(
        usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        response_metadata={},
    )
    record_token_usage(response)
    assert pop_token_usage() == {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
    }
    assert pop_token_usage() is None
    print("[OK] record_token_usage / pop_token_usage")


def test_agent_step_response_computed_fields() -> None:
    started = datetime.now(timezone.utc)
    ended = started + timedelta(milliseconds=250)
    step = AgentStepResponse(
        id=1,
        task_id=1,
        agent_name="planner",
        node_name="planning_node",
        status=StepStatus.SUCCESS,
        input_summary={"node": "planning_node"},
        output_summary={
            "token_usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            "related_files": ["src/a.py", "tests/test_a.py"],
        },
        error_message=None,
        started_at=started,
        ended_at=ended,
    )
    assert step.latency_ms == 250
    assert step.token_usage == {
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150,
    }
    assert step.related_files == ["src/a.py", "tests/test_a.py"]
    print("[OK] AgentStepResponse latency_ms / token_usage / related_files")


def main() -> None:
    test_extract_token_usage_usage_metadata()
    test_record_and_pop_token_usage()
    test_agent_step_response_computed_fields()
    print("\nAgent Trace 指标单测全部通过")


if __name__ == "__main__":
    main()

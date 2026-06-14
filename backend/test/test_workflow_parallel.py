# backend/test/test_workflow_parallel.py
# Purpose: verify the pre-approval agent group really runs concurrently.

import asyncio
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.models.agent_step import StepStatus
from app.services import workflow_runner


async def _run_parallel_smoke():
    classify_started = threading.Event()
    retrieve_started = threading.Event()

    def fake_classify_node(state):
        classify_started.set()
        assert retrieve_started.wait(1), "retrieve_context_node did not start in parallel"
        return {
            "current_agent": "issue_analyst",
            "current_node": "classify_issue_node",
            "issue_analysis": {"summary": "empty input bug"},
            "status": "running",
        }

    def fake_retrieve_node(state):
        retrieve_started.set()
        assert classify_started.wait(1), "classify_issue_node did not start in parallel"
        return {
            "current_agent": "code_retriever",
            "current_node": "retrieve_context_node",
            "retrieved_context": [{"file_path": "app.py", "score": 0.9}],
            "status": "running",
        }

    state, records = await workflow_runner._run_parallel_nodes(
        [
            ("classify_issue_node", fake_classify_node),
            ("retrieve_context_node", fake_retrieve_node),
        ],
        {
            "task_id": "1",
            "repo_url": "https://github.com/octocat/Hello-World",
            "issue_text": "empty input raises error",
            "status": "running",
        },
    )

    assert state["issue_analysis"]["summary"] == "empty input bug"
    assert state["retrieved_context"][0]["file_path"] == "app.py"
    assert [record["node_name"] for record in records] == [
        "classify_issue_node",
        "retrieve_context_node",
    ]
    assert all(record["status"] == StepStatus.SUCCESS for record in records)
    assert all("_state_updates" not in record for record in records)


def test_pre_approval_parallel_nodes_run_concurrently():
    asyncio.run(_run_parallel_smoke())

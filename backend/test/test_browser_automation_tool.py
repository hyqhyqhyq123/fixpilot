# backend/test/test_browser_automation_tool.py
# Purpose: verify the browser automation safety gate.

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.tools.browser_automation_tool import validate_browser_automation_request


def test_browser_automation_accepts_localhost_plan():
    plan = validate_browser_automation_request(
        "http://localhost:3000/tasks/1",
        [
            {"action": "navigate"},
            {"action": "click", "selector": "button[data-testid='approve']"},
            {"action": "type", "selector": "textarea", "text": "looks good"},
            {"action": "screenshot"},
        ],
    )

    assert plan.target_url == "http://localhost:3000/tasks/1"
    assert len(plan.actions) == 4
    assert "Only localhost" in plan.safety_notes[0]


def test_browser_automation_rejects_external_url():
    with pytest.raises(ValueError) as exc:
        validate_browser_automation_request(
            "https://example.com",
            [{"action": "navigate"}],
        )

    assert "localhost" in str(exc.value)


def test_browser_automation_rejects_unsafe_or_incomplete_actions():
    with pytest.raises(ValueError):
        validate_browser_automation_request(
            "http://127.0.0.1:3000",
            [{"action": "evaluate", "text": "alert(1)"}],
        )

    with pytest.raises(ValueError):
        validate_browser_automation_request(
            "http://127.0.0.1:3000",
            [{"action": "click"}],
        )

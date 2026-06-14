# backend/app/tools/browser_automation_tool.py
# Purpose: validate browser automation requests before any browser worker runs.

from __future__ import annotations

from urllib.parse import urlparse

from app.schemas.browser_automation import (
    BrowserAutomationAction,
    BrowserAutomationPlan,
)


ALLOWED_ACTIONS = {"navigate", "click", "type", "wait", "screenshot"}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
MAX_ACTIONS = 20


def _is_local_url(target_url: str) -> bool:
    parsed = urlparse(target_url)
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    return host in LOCAL_HOSTS or host.endswith(".localhost")


def validate_browser_automation_request(
    target_url: str,
    actions: list[dict],
) -> BrowserAutomationPlan:
    """
    Validate a browser automation request and return an executable plan shape.

    The actual browser worker is intentionally separate. This guard is the
    safety gate: FixPilot only allows local development targets and a small set
    of declarative actions, never arbitrary JavaScript or arbitrary websites.
    """
    if not _is_local_url(target_url):
        raise ValueError("Browser automation is limited to localhost targets")
    if len(actions) > MAX_ACTIONS:
        raise ValueError(f"Browser automation supports at most {MAX_ACTIONS} actions")

    parsed_actions: list[BrowserAutomationAction] = []
    for raw in actions:
        action_name = str(raw.get("action") or "").strip()
        if action_name not in ALLOWED_ACTIONS:
            raise ValueError(f"Unsupported browser action: {action_name}")

        action = BrowserAutomationAction.model_validate(raw)
        if action.action in {"click", "type"} and not action.selector:
            raise ValueError(f"{action.action} action requires selector")
        if action.action == "type" and action.text is None:
            raise ValueError("type action requires text")
        if action.timeout_ms is not None and action.timeout_ms < 0:
            raise ValueError("timeout_ms cannot be negative")
        parsed_actions.append(action)

    return BrowserAutomationPlan(
        target_url=target_url,
        actions=parsed_actions,
        safety_notes=[
            "Only localhost targets are allowed.",
            "Arbitrary JavaScript execution is not allowed.",
            "Execution must run in an isolated browser worker.",
        ],
    )

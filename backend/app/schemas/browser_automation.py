# backend/app/schemas/browser_automation.py
# Purpose: safe request shape for browser automation.

from pydantic import BaseModel, Field


class BrowserAutomationAction(BaseModel):
    action: str = Field(description="Allowed: navigate, click, type, wait, screenshot")
    selector: str | None = None
    text: str | None = None
    timeout_ms: int | None = None


class BrowserAutomationPlan(BaseModel):
    target_url: str
    actions: list[BrowserAutomationAction] = Field(default_factory=list)
    safety_notes: list[str] = Field(default_factory=list)

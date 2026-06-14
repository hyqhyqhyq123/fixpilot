# backend/app/schemas/security_fix.py
# Purpose: structured output for the Security Vulnerability Fix Agent.

from pydantic import BaseModel, Field


class SecurityFinding(BaseModel):
    file_path: str
    line_number: int
    rule_id: str
    severity: str
    evidence: str
    fix_hint: str


class SecurityFixReport(BaseModel):
    repo_path: str
    findings: list[SecurityFinding] = Field(default_factory=list)
    summary: str

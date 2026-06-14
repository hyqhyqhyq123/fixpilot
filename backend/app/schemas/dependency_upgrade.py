# backend/app/schemas/dependency_upgrade.py
# Purpose: structured output for the Dependency Upgrade Agent.

from pydantic import BaseModel, Field


class DependencyUpgradeCandidate(BaseModel):
    file_path: str
    ecosystem: str
    package_name: str
    current_spec: str
    recommendation: str
    reason: str


class DependencyUpgradeReport(BaseModel):
    repo_path: str
    candidates: list[DependencyUpgradeCandidate] = Field(default_factory=list)
    summary: str

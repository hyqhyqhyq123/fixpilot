# backend/app/schemas/devclaw.py
# Purpose: product-readiness profile for the DevClaw extension direction.

from pydantic import BaseModel, Field


class DevClawCapability(BaseModel):
    name: str
    status: str
    evidence: str


class DevClawProfile(BaseModel):
    product_name: str = "DevClaw"
    positioning: str
    capabilities: list[DevClawCapability] = Field(default_factory=list)
    safety_boundaries: list[str] = Field(default_factory=list)
    summary: str

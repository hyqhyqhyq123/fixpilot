# backend/app/agents/devclaw_profile.py
# Purpose: summarize FixPilot's readiness as a developer automation assistant.

from app.schemas.devclaw import DevClawCapability, DevClawProfile


def build_devclaw_profile() -> DevClawProfile:
    """
    Build a stable capability profile for the DevClaw extension.

    DevClaw is the productized direction of FixPilot: the same multi-agent
    coding workflow, presented as a broader developer automation assistant.
    This profile is deliberately static and testable, so it can be shown in a
    demo or used by a future product page/API without asking an LLM.
    """
    capabilities = [
        DevClawCapability(
            name="Multi-agent coding workflow",
            status="ready",
            evidence="LangGraph workflow with planning, approval, coding, testing, review, and PR draft.",
        ),
        DevClawCapability(
            name="GitHub integration",
            status="ready",
            evidence="Issue reading, PR creation, OAuth login, and Actions result reading are implemented.",
        ),
        DevClawCapability(
            name="Developer safety controls",
            status="ready",
            evidence="Human approval, tool permission levels, Docker test sandbox, and audit logs.",
        ),
        DevClawCapability(
            name="Maintenance assistants",
            status="ready",
            evidence="Dependency upgrade suggestions and security finding suggestions are available.",
        ),
        DevClawCapability(
            name="Local browser automation guard",
            status="guarded",
            evidence="Only localhost targets and declarative browser actions are accepted.",
        ),
    ]
    boundaries = [
        "Repository access beyond public repos is intentionally out of scope.",
        "Automatic merge is not supported; PR creation remains user-controlled.",
        "Arbitrary external browser automation is blocked by policy.",
    ]
    return DevClawProfile(
        positioning="Developer-facing multi-agent automation assistant built on FixPilot.",
        capabilities=capabilities,
        safety_boundaries=boundaries,
        summary="DevClaw profile is ready for demo packaging with explicit safety boundaries.",
    )

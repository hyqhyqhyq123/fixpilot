# backend/test/test_devclaw_profile.py
# Purpose: smoke test for the DevClaw product-readiness profile.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents.devclaw_profile import build_devclaw_profile


def test_devclaw_profile_lists_ready_capabilities_and_boundaries():
    profile = build_devclaw_profile()

    capability_names = {item.name for item in profile.capabilities}
    assert profile.product_name == "DevClaw"
    assert "Multi-agent coding workflow" in capability_names
    assert "GitHub integration" in capability_names
    assert "Maintenance assistants" in capability_names
    assert any("public repos" in item for item in profile.safety_boundaries)
    assert "ready" in profile.summary.lower()

# backend/test/test_dependency_upgrade_agent.py
# Purpose: smoke tests for the Dependency Upgrade Agent.

import shutil
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents.dependency_upgrade import analyze_dependency_upgrades


TMP_ROOT = Path(__file__).parent / "_tmp_dependency_upgrade"


def _new_repo() -> Path:
    root = TMP_ROOT / uuid4().hex
    root.mkdir(parents=True)
    return root


def _cleanup_repo(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)
    try:
        TMP_ROOT.rmdir()
    except OSError:
        pass


def test_dependency_upgrade_agent_scans_common_manifests():
    repo = _new_repo()
    try:
        (repo / "requirements.txt").write_text(
            "fastapi==0.100.0\npytest>=8\n",
            encoding="utf-8",
        )
        (repo / "package.json").write_text(
            '{"dependencies":{"react":"18.2.0"},"devDependencies":{"typescript":"^5.0.0"}}',
            encoding="utf-8",
        )
        (repo / "go.mod").write_text(
            "module example.com/demo\n\ngo 1.22\nrequire github.com/gin-gonic/gin v1.8.0\n",
            encoding="utf-8",
        )
        (repo / "pom.xml").write_text(
            """
<project>
  <dependencies>
    <dependency>
      <groupId>org.example</groupId>
      <artifactId>demo-lib</artifactId>
      <version>1.0.0</version>
    </dependency>
  </dependencies>
</project>
""",
            encoding="utf-8",
        )

        report = analyze_dependency_upgrades(str(repo))
    finally:
        _cleanup_repo(repo)

    by_name = {item.package_name: item for item in report.candidates}
    assert {"fastapi", "react", "github.com/gin-gonic/gin", "demo-lib"} <= set(by_name)
    assert by_name["fastapi"].ecosystem == "python"
    assert by_name["react"].file_path == "package.json"
    assert "go test" in by_name["github.com/gin-gonic/gin"].recommendation
    assert report.summary.startswith("Found 4")


def test_dependency_upgrade_agent_handles_repo_without_manifests():
    repo = _new_repo()
    try:
        report = analyze_dependency_upgrades(str(repo))
    finally:
        _cleanup_repo(repo)

    assert report.candidates == []
    assert "No dependency" in report.summary

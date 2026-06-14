# backend/app/agents/dependency_upgrade.py
# Purpose: inspect dependency files and suggest safe upgrade review items.

from __future__ import annotations

import json
import re
from pathlib import Path

from app.schemas.dependency_upgrade import (
    DependencyUpgradeCandidate,
    DependencyUpgradeReport,
)


_REQ_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9_.-]+)\s*(?P<op>==|~=|>=|<=|>|<)?\s*(?P<version>[^;\s]+)?"
)


def _candidate(
    file_path: str,
    ecosystem: str,
    package_name: str,
    current_spec: str,
    recommendation: str,
    reason: str,
) -> DependencyUpgradeCandidate:
    return DependencyUpgradeCandidate(
        file_path=file_path,
        ecosystem=ecosystem,
        package_name=package_name,
        current_spec=current_spec,
        recommendation=recommendation,
        reason=reason,
    )


def _scan_requirements(root: Path) -> list[DependencyUpgradeCandidate]:
    path = root / "requirements.txt"
    if not path.exists():
        return []

    candidates: list[DependencyUpgradeCandidate] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _REQ_RE.match(stripped)
        if not match:
            continue
        name = match.group("name")
        op = match.group("op") or ""
        version = match.group("version") or ""
        if op == "==":
            candidates.append(
                _candidate(
                    "requirements.txt",
                    "python",
                    name,
                    stripped,
                    f"Review latest compatible patch/minor version for {name}.",
                    "Pinned Python dependency can block security and bugfix updates.",
                )
            )
    return candidates


def _scan_package_json(root: Path) -> list[DependencyUpgradeCandidate]:
    path = root / "package.json"
    if not path.exists():
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except json.JSONDecodeError:
        return []

    candidates: list[DependencyUpgradeCandidate] = []
    for section in ("dependencies", "devDependencies"):
        deps = data.get(section) or {}
        for name, spec in deps.items():
            if not isinstance(spec, str):
                continue
            if spec and spec[0].isdigit():
                candidates.append(
                    _candidate(
                        "package.json",
                        "nodejs",
                        name,
                        spec,
                        f"Consider using a compatible range such as ^{spec}, then run npm test.",
                        "Exact npm dependency versions often miss compatible patch updates.",
                    )
                )
    return candidates


def _scan_go_mod(root: Path) -> list[DependencyUpgradeCandidate]:
    path = root / "go.mod"
    if not path.exists():
        return []

    candidates: list[DependencyUpgradeCandidate] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("module ") or stripped.startswith("go "):
            continue
        parts = stripped.split()
        if parts[0] == "require" and len(parts) >= 3:
            package_name = parts[1]
            version = parts[2]
        elif len(parts) >= 2:
            package_name = parts[0]
            version = parts[1]
        else:
            continue

        if version.startswith("v"):
            candidates.append(
                _candidate(
                    "go.mod",
                    "go",
                    package_name,
                    version,
                    f"Run go get -u=patch {package_name} and then go test ./...",
                    "Go modules can usually be patch-upgraded with test verification.",
                )
            )
    return candidates


def _scan_pom_xml(root: Path) -> list[DependencyUpgradeCandidate]:
    path = root / "pom.xml"
    if not path.exists():
        return []

    content = path.read_text(encoding="utf-8", errors="ignore")
    candidates: list[DependencyUpgradeCandidate] = []
    for match in re.finditer(
        r"<dependency>.*?<artifactId>(?P<artifact>[^<]+)</artifactId>.*?"
        r"<version>(?P<version>[^<]+)</version>.*?</dependency>",
        content,
        flags=re.DOTALL,
    ):
        artifact = match.group("artifact").strip()
        version = match.group("version").strip()
        candidates.append(
            _candidate(
                "pom.xml",
                "java-maven",
                artifact,
                version,
                f"Review Maven metadata for a compatible version, then run mvn test.",
                "Explicit Maven dependency versions should be reviewed for fixes.",
            )
        )
    return candidates


def analyze_dependency_upgrades(repo_path: str) -> DependencyUpgradeReport:
    """
    Scan common dependency manifests and return upgrade review suggestions.

    This Agent intentionally does not edit files or call package registries.
    Dependency upgrades can break projects, so FixPilot first produces a clear
    review list that a later approved Coder step can apply safely.
    """
    root = Path(repo_path)
    candidates: list[DependencyUpgradeCandidate] = []
    candidates.extend(_scan_requirements(root))
    candidates.extend(_scan_package_json(root))
    candidates.extend(_scan_go_mod(root))
    candidates.extend(_scan_pom_xml(root))

    summary = (
        f"Found {len(candidates)} dependency upgrade review item(s)."
        if candidates
        else "No dependency upgrade review items found."
    )
    return DependencyUpgradeReport(
        repo_path=str(root),
        candidates=candidates,
        summary=summary,
    )

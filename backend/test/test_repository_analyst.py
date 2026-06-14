# backend/test/test_repository_analyst.py
# Purpose: smoke tests for the Repository Analyst Agent.

import sys
import shutil
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents.repository_analyst import analyze_repository, clone_repository
from app.graph import nodes
from app.graph.state import FixPilotState


TMP_ROOT = Path(__file__).parent / "_tmp_repository_analyst"


def _new_test_repo() -> Path:
    root = TMP_ROOT / uuid4().hex
    root.mkdir(parents=True)
    _make_python_repo(root)
    return root


def _new_empty_test_repo() -> Path:
    root = TMP_ROOT / uuid4().hex
    root.mkdir(parents=True)
    return root


def _cleanup_test_repo(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)
    try:
        TMP_ROOT.rmdir()
    except OSError:
        pass


def _make_python_repo(root: Path) -> None:
    """Create a tiny Python project that the analyzer can inspect quickly."""

    (root / "pyproject.toml").write_text(
        """
[project]
name = "demo"
dependencies = ["pytest"]
""".strip(),
        encoding="utf-8",
    )
    (root / "app.py").write_text(
        "def hello() -> str:\n    return 'hello'\n",
        encoding="utf-8",
    )
    (root / "pytest.ini").write_text(
        "[pytest]\npythonpath = .\n",
        encoding="utf-8",
    )
    tests_dir = root / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_app.py").write_text(
        "from app import hello\n\n\ndef test_hello():\n    assert hello() == 'hello'\n",
        encoding="utf-8",
    )


def test_clone_repository_rejects_invalid_url():
    result = clone_repository(task_id=99001, repo_url="file:///tmp/not-a-github-repo")

    assert result.success is False
    assert result.repo_path is None
    assert result.error


def test_analyze_repository_returns_workflow_ready_shape():
    repo_path = _new_test_repo()
    try:
        result = analyze_repository(str(repo_path))
    finally:
        _cleanup_test_repo(repo_path)

    assert result.project_info.primary_type == "python"
    assert result.project_info.primary_language == "Python"
    assert result.test_command == "pytest"
    assert "tests" in result.project_info.test_directories
    assert result.file_tree_summary
    assert result.total_files >= 3


def test_analyze_repo_node_uses_repository_analyst():
    repo_path = _new_test_repo()
    try:
        state = FixPilotState(
            task_id="1",
            repo_url="https://github.com/example/demo",
            issue_text="demo issue",
            repo_path=str(repo_path),
        )

        updates = nodes.analyze_repo_node(state)
    finally:
        _cleanup_test_repo(repo_path)

    assert updates["current_agent"] == "repository_analyst"
    assert updates["current_node"] == "analyze_repo_node"
    assert updates["project_info"]["primary_type"] == "python"
    assert updates["test_command"] == "pytest"


def test_clone_repo_node_reports_invalid_url_without_network():
    state = FixPilotState(
        task_id="99002",
        repo_url="file:///tmp/not-a-github-repo",
        issue_text="demo issue",
    )

    updates = nodes.clone_repo_node(state)

    assert updates["current_agent"] == "repository_analyst"
    assert updates["current_node"] == "clone_repo_node"
    assert updates["status"] == "failed"
    assert updates["final_status"] == "failed"


def test_repository_analyst_detects_v2_language_matrix():
    cases = [
        (
            "python",
            {"pyproject.toml": "[project]\nname = 'demo'\n", "pytest.ini": "[pytest]\n"},
            "python",
            "Python",
            "pytest",
        ),
        (
            "typescript",
            {
                "package.json": (
                    '{"scripts":{"test":"vitest"},'
                    '"devDependencies":{"typescript":"^5.0.0","vitest":"^1.0.0"}}'
                ),
                "src/index.ts": "export const answer = 42;\n",
            },
            "nodejs",
            "JavaScript/TypeScript",
            "npm test",
        ),
        (
            "go",
            {"go.mod": "module example.com/demo\n\ngo 1.22\n", "main.go": "package main\n"},
            "go",
            "Go",
            "go test ./...",
        ),
        (
            "java",
            {
                "pom.xml": "<project><modelVersion>4.0.0</modelVersion></project>\n",
                "src/main/java/App.java": "class App {}\n",
            },
            "java-maven",
            "Java",
            "mvn test",
        ),
    ]

    for name, files, expected_type, expected_language, expected_test_command in cases:
        repo_path = _new_empty_test_repo()
        try:
            for relative_path, content in files.items():
                target = repo_path / relative_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")

            result = analyze_repository(str(repo_path))
        finally:
            _cleanup_test_repo(repo_path)

        assert result.project_info.primary_type == expected_type, name
        assert result.project_info.primary_language == expected_language, name
        assert result.test_command == expected_test_command, name

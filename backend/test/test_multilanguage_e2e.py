# backend/test/test_multilanguage_e2e.py
# Purpose: local multi-language repository E2E smoke tests.

import shutil
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents.repository_analyst import analyze_repository
from app.graph import nodes
from app.graph.state import FixPilotState
from app.services import workflow_runner


TMP_ROOT = Path(__file__).parent / "_tmp_multilanguage_e2e"


def _new_repo(name: str) -> Path:
    root = TMP_ROOT / f"{name}_{uuid4().hex}"
    root.mkdir(parents=True)
    return root


def _cleanup_repo(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)
    try:
        TMP_ROOT.rmdir()
    except OSError:
        pass


def _write(root: Path, relative_path: str, content: str) -> None:
    target = root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content.strip() + "\n", encoding="utf-8")


def _make_python_repo(root: Path) -> None:
    _write(
        root,
        "pyproject.toml",
        """
[project]
name = "fixpilot-python-demo"
dependencies = ["pytest>=8", "ruff>=0.6", "mypy>=1"]
""",
    )
    _write(root, "requirements.txt", "pytest\nruff\nmypy")
    _write(root, "pytest.ini", "[pytest]\npythonpath = src")
    _write(root, "src/demo/app.py", "def add(a: int, b: int) -> int:\n    return a + b")
    _write(
        root,
        "tests/test_app.py",
        "from demo.app import add\n\n\ndef test_add():\n    assert add(1, 2) == 3",
    )


def _make_typescript_repo(root: Path) -> None:
    _write(
        root,
        "package.json",
        """
{
  "scripts": {"test": "vitest", "typecheck": "tsc --noEmit"},
  "dependencies": {"react": "^18.0.0"},
  "devDependencies": {
    "typescript": "^5.0.0",
    "vitest": "^1.0.0",
    "eslint": "^9.0.0"
  }
}
""",
    )
    _write(root, "tsconfig.json", '{"compilerOptions":{"strict":true}}')
    _write(root, "src/index.ts", "export const add = (a: number, b: number) => a + b;")
    _write(
        root,
        "__tests__/index.test.ts",
        "import { add } from '../src';\n\nit('adds numbers', () => expect(add(1, 2)).toBe(3));",
    )


def _make_go_repo(root: Path) -> None:
    _write(root, "go.mod", "module example.com/fixpilot-go-demo\n\ngo 1.22")
    _write(root, "main.go", "package main\n\nfunc Add(a int, b int) int { return a + b }")
    _write(
        root,
        "main_test.go",
        "package main\n\nimport \"testing\"\n\nfunc TestAdd(t *testing.T) { if Add(1, 2) != 3 { t.Fatal(\"bad add\") } }",
    )


def _make_java_repo(root: Path) -> None:
    _write(
        root,
        "pom.xml",
        """
<project>
  <modelVersion>4.0.0</modelVersion>
  <groupId>dev.fixpilot</groupId>
  <artifactId>java-demo</artifactId>
  <version>1.0.0</version>
</project>
""",
    )
    _write(
        root,
        "src/main/java/dev/fixpilot/App.java",
        "package dev.fixpilot;\n\npublic class App { public int add(int a, int b) { return a + b; } }",
    )
    _write(
        root,
        "src/test/java/dev/fixpilot/AppTest.java",
        "package dev.fixpilot;\n\nclass AppTest { }",
    )


def test_multilanguage_repositories_flow_into_workflow_state():
    cases = [
        ("python", _make_python_repo, "python", "Python", "pytest", "mypy ."),
        (
            "typescript",
            _make_typescript_repo,
            "nodejs",
            "JavaScript/TypeScript",
            "npm test",
            "npx tsc --noEmit",
        ),
        ("go", _make_go_repo, "go", "Go", "go test ./...", None),
        ("java", _make_java_repo, "java-maven", "Java", "mvn test", None),
    ]

    for name, make_repo, expected_type, expected_language, expected_test, expected_typecheck in cases:
        repo_path = _new_repo(name)
        try:
            make_repo(repo_path)
            analysis = analyze_repository(str(repo_path))
            assert analysis.project_info.primary_type == expected_type, name
            assert analysis.project_info.primary_language == expected_language, name
            assert analysis.test_command == expected_test, name
            if expected_typecheck:
                assert analysis.typecheck_command == expected_typecheck, name

            state = FixPilotState(
                task_id="1",
                repo_url="https://github.com/example/demo",
                issue_text=f"{name} E2E issue",
                repo_path=str(repo_path),
                retrieved_context=[],
                edit_history=[],
                test_results=[],
            )
            updates = nodes.analyze_repo_node(state)
            merged_state = {**state, **updates}
            checks = workflow_runner._collect_docker_checks_from_state(merged_state)

            assert updates["project_info"]["primary_type"] == expected_type, name
            assert ("test", expected_test) in checks, name
            if expected_typecheck:
                assert ("typecheck", expected_typecheck) in checks, name
            assert analysis.file_tree_summary
        finally:
            _cleanup_repo(repo_path)

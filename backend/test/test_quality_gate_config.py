import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_pyproject_quality_gate_sections_exist():
    data = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "ruff" in data["tool"]
    assert "mypy" in data["tool"]
    assert "coverage" in data["tool"]
    assert data["tool"]["coverage"]["report"]["fail_under"] >= 50
    assert "backend/test" in data["tool"]["pytest"]["ini_options"]["testpaths"]
    print("[OK] pyproject.toml 包含 Ruff / mypy / coverage / pytest 配置")


def test_pre_commit_config_contains_quality_hooks():
    content = (PROJECT_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert "ruff-pre-commit" in content
    assert "mirrors-mypy" in content
    assert "backend focused tests" in content
    print("[OK] pre-commit 配置包含 Ruff、mypy 和后端聚焦测试")


def test_github_actions_ci_contains_backend_and_frontend_gates():
    content = (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    assert "Ruff lint" in content
    assert "Mypy" in content
    assert "Alembic migration smoke" in content
    assert "Focused pytest suite" in content
    assert "Focused coverage report" in content
    assert "Lint frontend" in content
    assert "Build frontend" in content
    print("[OK] GitHub Actions 覆盖后端 lint/type/migration/test 和前端 lint/build")


def test_dev_requirements_include_quality_tools():
    content = (PROJECT_ROOT / "backend" / "requirements-dev.txt").read_text(
        encoding="utf-8"
    )
    for package in ("pytest-cov", "coverage", "ruff", "mypy", "pre-commit"):
        assert package in content
    print("[OK] requirements-dev.txt 包含本地质量门禁依赖")

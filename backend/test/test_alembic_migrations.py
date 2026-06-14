import sys
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

sys.path.insert(0, str(Path(__file__).parent.parent))


def _alembic_config(database_url: str) -> Config:
    backend_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def test_alembic_upgrade_and_downgrade(monkeypatch):
    tmp_root = Path(__file__).parent / "_tmp_alembic"
    tmp_root.mkdir(exist_ok=True)
    db_path = tmp_root / f"{uuid4().hex}.db"
    database_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("FIXPILOT_ALEMBIC_DATABASE_URL", database_url)
    cfg = _alembic_config(database_url)

    command.upgrade(cfg, "head")

    engine = create_engine(database_url)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert "fix_tasks" in tables
    assert "agent_steps" in tables
    assert "tool_calls" in tables
    assert "workflow_checkpoints" in tables
    assert "task_status_transitions" in tables
    assert "alembic_version" in tables

    command.downgrade(cfg, "base")

    inspector = inspect(engine)
    tables_after_downgrade = set(inspector.get_table_names())
    assert "fix_tasks" not in tables_after_downgrade
    assert "agent_steps" not in tables_after_downgrade
    assert "alembic_version" in tables_after_downgrade
    engine.dispose()
    db_path.unlink(missing_ok=True)
    print("[OK] Alembic initial schema upgrade/downgrade 可执行")

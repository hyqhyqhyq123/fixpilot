# backend/test/test_edit_file_tool.py
# 运行：python test/test_edit_file_tool.py

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.tools.edit_file_tool import edit_file, rollback_file


def test_edit_and_rollback():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        target = repo / "hello.txt"
        target.write_text("old", encoding="utf-8")

        allowed = ["hello.txt"]
        result = edit_file(
            repo_path=str(repo),
            file_path="hello.txt",
            new_content="new content",
            allowed_files=allowed,
        )
        assert result["success"], result.get("error")
        assert target.read_text(encoding="utf-8") == "new content"
        assert "new content" in (result.get("diff") or "")

        rollback_file(str(repo), "hello.txt", result["before_content"])
        assert target.read_text(encoding="utf-8") == "old"
        print("[OK] 编辑与回滚成功")


def test_not_in_allowed_list():
    with tempfile.TemporaryDirectory() as tmp:
        result = edit_file(
            repo_path=tmp,
            file_path="secret.py",
            new_content="x",
            allowed_files=["other.py"],
        )
        assert not result["success"]
        print("[OK] 白名单校验生效")


if __name__ == "__main__":
    test_edit_and_rollback()
    test_not_in_allowed_list()
    print("\nedit_file_tool 测试通过")

# backend/test/test_read_file_tool.py
# 运行：python test/test_read_file_tool.py

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.tools.read_file_tool import read_file


def test_read_existing_file():
    repo = str(Path(__file__).parent.parent)
    result = read_file(repo, "app/main.py")
    assert result["error"] is None, result.get("error")
    assert "FastAPI" in result["content"] or len(result["content"]) > 0
    print("[OK] 读取 app/main.py 成功")


def test_path_escape_blocked():
    repo = str(Path(__file__).parent.parent)
    result = read_file(repo, "../../../etc/passwd")
    assert result["error"] is not None
    print("[OK] 路径逃逸被拦截")


if __name__ == "__main__":
    test_read_existing_file()
    test_path_escape_blocked()
    print("\nread_file_tool 测试通过")

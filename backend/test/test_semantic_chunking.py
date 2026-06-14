# backend/test/test_semantic_chunking.py
# Purpose: verify semantic-search chunking without calling embeddings.

import shutil
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.tools.semantic_search_tool import _split_file_into_chunks


TMP_ROOT = Path(__file__).parent / "_tmp_semantic_chunking"


def _new_repo() -> Path:
    repo = TMP_ROOT / uuid4().hex
    repo.mkdir(parents=True)
    return repo


def _cleanup_repo(repo: Path) -> None:
    shutil.rmtree(repo, ignore_errors=True)
    try:
        TMP_ROOT.rmdir()
    except OSError:
        pass


def test_python_chunking_prefers_def_and_class_boundaries():
    repo = _new_repo()
    try:
        target = repo / "service.py"
        target.write_text(
            "\n".join(
                [
                    "def first():",
                    "    return 1",
                    "",
                    "class Service:",
                    "    def run(self):",
                    "        return 2",
                ]
            ),
            encoding="utf-8",
        )

        chunks = _split_file_into_chunks(target, repo, chunk_lines=50)
    finally:
        _cleanup_repo(repo)

    assert [(chunk["line_start"], chunk["line_end"]) for chunk in chunks] == [
        (1, 2),
        (4, 6),
    ]
    assert all(chunk["file_path"] == "service.py" for chunk in chunks)
    assert [chunk["language"] for chunk in chunks] == ["python", "python"]
    assert [chunk["symbol_name"] for chunk in chunks] == ["first", "Service"]
    assert "def run" in chunks[1]["content"]


def test_python_ast_chunking_keeps_decorators_with_function():
    repo = _new_repo()
    try:
        target = repo / "routes.py"
        target.write_text(
            "\n".join(
                [
                    '@router.get("/items")',
                    "async def list_items():",
                    "    return []",
                ]
            ),
            encoding="utf-8",
        )

        chunks = _split_file_into_chunks(target, repo, chunk_lines=50)
    finally:
        _cleanup_repo(repo)

    assert len(chunks) == 1
    assert chunks[0]["language"] == "python"
    assert chunks[0]["symbol_name"] == "list_items"
    assert chunks[0]["line_start"] == 1
    assert chunks[0]["line_end"] == 3
    assert chunks[0]["content"].startswith('@router.get("/items")')


def test_typescript_chunking_prefers_function_and_class_boundaries():
    repo = _new_repo()
    try:
        target = repo / "src" / "index.ts"
        target.parent.mkdir()
        target.write_text(
            "\n".join(
                [
                    "export function parseInput() {",
                    "  return true;",
                    "}",
                    "export class Runner {",
                    "  run() { return true; }",
                    "}",
                ]
            ),
            encoding="utf-8",
        )

        chunks = _split_file_into_chunks(target, repo, chunk_lines=50)
    finally:
        _cleanup_repo(repo)

    assert [chunk["line_start"] for chunk in chunks] == [1, 4]
    assert chunks[0]["file_path"] == "src/index.ts"
    assert [chunk["language"] for chunk in chunks] == ["typescript", "typescript"]
    assert [chunk["symbol_name"] for chunk in chunks] == ["parseInput", "Runner"]


def test_long_definition_still_uses_line_limit():
    repo = _new_repo()
    try:
        target = repo / "long.py"
        target.write_text(
            "\n".join(["def long_function():"] + [f"    x{i} = {i}" for i in range(12)]),
            encoding="utf-8",
        )

        chunks = _split_file_into_chunks(target, repo, chunk_lines=5)
    finally:
        _cleanup_repo(repo)

    assert len(chunks) == 3
    assert all(chunk["symbol_name"] == "long_function" for chunk in chunks)
    assert all((chunk["line_end"] - chunk["line_start"] + 1) <= 5 for chunk in chunks)

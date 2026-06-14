# backend/test/smoke_real_issue_plan_commit.py
# 真实 issue 冒烟测试：验证真实 GitHub repo + issue 能走到“计划 + commit message”。
#
# 运行方式（在 backend 目录下）：
#   python test/smoke_real_issue_plan_commit.py
#
# 这个脚本故意不改代码、不运行测试、不创建 PR。
# 目的只是验证前半段链路：真实 issue -> clone -> repo 分析 -> 检索 -> Planner -> Commit Message。

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.issue_analyst import analyze_issue
from app.agents.planner import generate_fix_plan
from app.agents.pr_writer import generate_pr_description
from app.schemas.code_retrieval import CodeRetrievalRequest
from app.schemas.issue_analysis import IssueAnalysisRequest
from app.tools.repo_analysis_tool import detect_project_info, get_file_tree_text, list_files
from app.tools.repo_clone_tool import clone_repo
from app.agents.code_retriever import retrieve_code


TASK_ID = 389902
REPO_URL = "https://github.com/pallets/itsdangerous"
ISSUE_URL = "https://github.com/pallets/itsdangerous/issues/389"

# 真实来源：GitHub issue #389。
# 固定正文可以避免匿名 GitHub API rate limit；repo clone 仍然访问真实 GitHub。
ISSUE_TEXT = """Title: serializer_kwargs are missing in load_payload function

Source: https://github.com/pallets/itsdangerous/issues/389

When using this library with a serializer, it's sometimes necessary to provide
the serializer with additional kwargs. It works great within the dump_payload
function. However, load_payload function doesn't supply any stored
serializer_kwargs into the serializer. I'm not sure if it's done intentionally
or just forgotten.

Here's the code to reproduce the problem:

    import jsonpickle
    from itsdangerous import Serializer

    key = '123'
    data = {0: 'foo', 1: "bar"}
    s = Serializer(key, serializer=jsonpickle, serializer_kwargs={"keys": True})

    signed = s.dumps(data)
    unsigned = s.loads(signed)
    print(unsigned)
    # {'json://0': 'foo', 'json://1': 'bar'} - because the kwarg "keys": True
    # was not passed to the loading function

The expected behavior would be to provide load_payload with **serializer_kwargs
and return {0: 'foo', 1: 'bar'} in this example.

Environment:
- Python version: 3.12
- ItsDangerous version: 2.2.0
"""


def main() -> None:
    print("=== FixPilot real issue smoke: plan + commit message ===")
    print(f"repo: {REPO_URL}")
    print(f"issue: {ISSUE_URL}")

    print("\n[1/6] clone repo")
    clone_result = clone_repo(task_id=TASK_ID, repo_url=REPO_URL)
    if not clone_result["success"]:
        raise RuntimeError(clone_result["error"])
    repo_path = clone_result["repo_path"]
    print(f"repo_path: {repo_path}")

    print("\n[2/6] analyze repo")
    project_info = detect_project_info(repo_path)
    file_tree = get_file_tree_text(list_files(repo_path))
    repo_analysis = project_info.model_dump()
    repo_analysis["file_tree"] = file_tree
    print(
        "project:",
        json.dumps(
            {
                "primary_language": project_info.primary_language,
                "primary_type": project_info.primary_type,
                "test_command": project_info.test_command,
            },
            ensure_ascii=False,
        ),
    )

    print("\n[3/6] analyze real issue with LLM")
    issue_analysis = analyze_issue(
        IssueAnalysisRequest(
            issue_text=ISSUE_TEXT,
            repo_context=(
                f"Repository: {REPO_URL}\n"
                f"Primary language: {project_info.primary_language}\n"
                f"Test command: {project_info.test_command or 'unknown'}"
            ),
        )
    )
    print("issue_summary:", issue_analysis.summary)

    print("\n[4/6] retrieve related code with keyword search")
    retrieval = retrieve_code(
        CodeRetrievalRequest(
            repo_path=repo_path,
            query_text=ISSUE_TEXT,
            keywords=[
                "serializer_kwargs",
                "load_payload",
                "dump_payload",
                "Serializer",
                "loads",
            ],
            search_method="keyword",
            max_files=5,
        )
    )
    print("retrieved_files:", [item.file_path for item in retrieval.retrieved_files])
    if not retrieval.retrieved_files:
        raise RuntimeError("关键词检索没有返回任何相关文件")

    print("\n[5/6] generate fix plan with Planner LLM")
    plan = generate_fix_plan(
        issue_text=ISSUE_TEXT,
        issue_analysis=issue_analysis.model_dump(),
        retrieved_result=retrieval.model_dump(),
        repo_analysis=repo_analysis,
    )
    print("problem_summary:", plan.problem_summary)
    print("files_to_modify:", [item.path for item in plan.files_to_modify])
    print("test_plan:", plan.test_plan)
    if not plan.files_to_modify:
        raise RuntimeError("Planner 没有给出需要修改的文件")

    print("\n[6/6] generate commit message")
    edit_history = [{"file_path": item.path} for item in plan.files_to_modify]
    pr = generate_pr_description(
        issue_text=ISSUE_TEXT,
        plan=plan.model_dump(),
        edit_history=edit_history,
        current_diff="Plan-only smoke test: no code was changed.",
        test_results=[],
        review_result={"risk_level": "unknown", "review_comments": []},
    )
    print("commit_message:", pr.commit_message)
    if not pr.commit_message or ":" not in pr.commit_message:
        raise RuntimeError("commit message 不符合 conventional commits 基本格式")
    if "## Commit Message" not in pr.full_markdown:
        raise RuntimeError("PR Writer 输出中缺少 ## Commit Message 章节")

    print("\n[PASS] real issue smoke completed")


if __name__ == "__main__":
    main()

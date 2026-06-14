# backend/test/smoke_real_issue_coder_docker.py
# 真实 issue 冒烟测试：执行 Coder 改代码，并用 Docker 验证修复效果。
#
# 运行方式（在 backend 目录下）：
#   python test/smoke_real_issue_coder_docker.py
#
# 安全边界：
# - 只修改 workspaces/task_<id>/itsdangerous 里的克隆仓库
# - Docker 使用 run_tests_tool，默认 --network none
# - 不 push、不创建 PR

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.code_retriever import retrieve_code
from app.agents.coder import apply_approved_plan
from app.agents.issue_analyst import analyze_issue
from app.agents.planner import generate_fix_plan
from app.agents.pr_writer import generate_pr_description
from app.schemas.code_retrieval import CodeRetrievalRequest
from app.schemas.issue_analysis import IssueAnalysisRequest
from app.tools.repo_analysis_tool import detect_project_info, get_file_tree_text, list_files
from app.tools.repo_clone_tool import clone_repo
from app.tools.run_tests_tool import run_tests_in_docker


REPO_URL = "https://github.com/pallets/itsdangerous"
ISSUE_URL = "https://github.com/pallets/itsdangerous/issues/389"

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

# 这个测试不用安装 jsonpickle，而是做一个最小 serializer。
# 如果 load_payload 没把 serializer_kwargs 传给 loads，测试会失败。
TARGETED_DOCKER_COMMAND = r"""python - <<'PY'
import sys

sys.path.insert(0, "src")
from itsdangerous import Serializer


class RequiresKwSerializer:
    def dumps(self, obj, **kwargs):
        # Serializer.__init__ 会用 dumps({}) 探测返回类型；这个探测阶段不会传 kwargs。
        # 所以这里不强制 dumps 必须收到 marker，测试重点放在 load_payload -> loads。
        return repr(obj)

    def loads(self, payload, **kwargs):
        if kwargs.get("marker") != "ok":
            raise AssertionError(f"loads missing marker: {kwargs!r}")
        return eval(payload)


data = {"answer": 42}
serializer = Serializer(
    "secret-key",
    serializer=RequiresKwSerializer(),
    serializer_kwargs={"marker": "ok"},
)
assert serializer.loads(serializer.dumps(data)) == data
print("serializer_kwargs_ok")
PY"""


def _run_targeted_docker(repo_path: str, label: str):
    print(f"\n[{label}] Docker targeted regression")
    result = run_tests_in_docker(
        repo_path=repo_path,
        command=TARGETED_DOCKER_COMMAND,
        project_type="python",
        timeout_seconds=120,
    )
    print(
        json.dumps(
            {
                "passed": result.passed,
                "exit_code": result.exit_code,
                "error_message": result.error_message,
                "stdout": result.stdout[-500:],
                "stderr": result.stderr[-500:],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return result


def main() -> None:
    task_id = int(time.time())
    print("=== FixPilot real issue smoke: coder + docker ===")
    print(f"repo: {REPO_URL}")
    print(f"issue: {ISSUE_URL}")
    print(f"task_id: {task_id}")

    print("\n[1/8] clone clean repo")
    clone_result = clone_repo(task_id=task_id, repo_url=REPO_URL)
    if not clone_result["success"]:
        raise RuntimeError(clone_result["error"])
    repo_path = clone_result["repo_path"]
    print(f"repo_path: {repo_path}")

    print("\n[2/8] analyze repo")
    project_info = detect_project_info(repo_path)
    repo_analysis = project_info.model_dump()
    repo_analysis["file_tree"] = get_file_tree_text(list_files(repo_path))
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

    print("\n[3/8] baseline Docker test before Coder")
    before = _run_targeted_docker(repo_path, "before")
    if before.passed:
        print("[WARN] 原始仓库已通过 targeted case，可能 upstream 已修复；仍继续跑 Coder。")

    print("\n[4/8] analyze issue with LLM")
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

    print("\n[5/8] retrieve related code")
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

    print("\n[6/8] generate plan with Planner LLM")
    plan = generate_fix_plan(
        issue_text=ISSUE_TEXT,
        issue_analysis=issue_analysis.model_dump(),
        retrieved_result=retrieval.model_dump(),
        repo_analysis=repo_analysis,
    )
    plan_dict = plan.model_dump()
    allowed_files = sorted(
        {item.path for item in plan.files_to_modify}
        | {item.path for item in plan.files_to_add}
    )
    print("problem_summary:", plan.problem_summary)
    print("allowed_files:", allowed_files)
    if "src/itsdangerous/serializer.py" not in allowed_files:
        raise RuntimeError("Planner 没有允许修改核心文件 src/itsdangerous/serializer.py")

    print("\n[7/8] apply approved plan with Coder LLM")
    coder_result = apply_approved_plan(
        repo_path=repo_path,
        issue_text=ISSUE_TEXT,
        plan=plan_dict,
        allowed_files=allowed_files,
        retry_index=0,
    )
    if not coder_result.success:
        raise RuntimeError(coder_result.error_message)
    print("edited_files:", coder_result.edited_files)
    print("diff_excerpt:")
    print((coder_result.combined_diff or "")[:2000])

    print("\n[8/8] Docker test after Coder")
    after = _run_targeted_docker(repo_path, "after")
    if not after.passed:
        raise RuntimeError("Coder 修改后 Docker targeted regression 仍未通过")

    pr = generate_pr_description(
        issue_text=ISSUE_TEXT,
        plan=plan_dict,
        edit_history=coder_result.edit_records,
        current_diff=coder_result.combined_diff,
        test_results=[
            {
                "passed": after.passed,
                "command": TARGETED_DOCKER_COMMAND,
                "check_type": "test",
            }
        ],
        review_result={"risk_level": "unknown", "review_comments": []},
    )
    print("\ncommit_message:", pr.commit_message)
    print("[PASS] real issue coder + docker smoke completed")


if __name__ == "__main__":
    main()

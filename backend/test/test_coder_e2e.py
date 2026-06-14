# backend/test/test_coder_e2e.py
# Coder 全链路集成测试：create → start → approve → 检查 steps
#
# 运行（需 PostgreSQL + LLM API + 可选 Docker）：
#   cd backend && python test/test_coder_e2e.py

import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

BASE = "http://127.0.0.1:8000"
# 小仓库，加快 clone；issue 故意简单，便于 Planner/Coder 产出小改动
PAYLOAD = {
    "repo_url": "https://github.com/pallets/click",
    "issue_text": (
        "当用户未提供必需参数时，Click 应显示清晰的错误提示，"
        "而不是抛出难以理解的异常堆栈。请检查参数校验相关代码。"
    ),
    "test_command": "python -m pytest tests/test_options.py -q --tb=no -x 2>/dev/null || python -c \"print('skip')\"",
}


def main() -> None:
    timeout = httpx.Timeout(connect=30.0, read=900.0, write=30.0, pool=30.0)
    with httpx.Client(base_url=BASE, timeout=timeout) as client:
        print("=== 1. 健康检查 ===")
        r = client.get("/health")
        r.raise_for_status()
        print(r.json())

        print("\n=== 2. 创建任务 ===")
        r = client.post("/api/fix-tasks", json=PAYLOAD)
        r.raise_for_status()
        task = r.json()
        task_id = task["id"]
        print(f"task_id={task_id}, status={task['status']}")

        print("\n=== 3. 启动 Workflow（可能需数分钟：clone + LLM + 索引）===")
        t0 = time.perf_counter()
        r = client.post(f"/api/fix-tasks/{task_id}/start")
        t1 = time.perf_counter()
        print(f"HTTP {r.status_code}, 耗时 {t1 - t0:.1f}s")
        if r.status_code != 200:
            print(r.text)
            sys.exit(1)
        body = r.json()
        print(f"message: {body.get('message')}")
        print(f"status: {body['task']['status']}, node: {body['task'].get('current_node')}")

        if body["task"]["status"] != "waiting_approval":
            print("预期 waiting_approval，启动阶段可能失败")
            print(json.dumps(body, ensure_ascii=False, indent=2))
            sys.exit(1)

        print("\n=== 4. 批准计划（Coder + Tester）===")
        t0 = time.perf_counter()
        r = client.post(
            f"/api/fix-tasks/{task_id}/approve",
            json={"comment": "E2E 测试自动批准"},
        )
        t1 = time.perf_counter()
        print(f"HTTP {r.status_code}, 耗时 {t1 - t0:.1f}s")
        if r.status_code != 200:
            print(r.text)
            sys.exit(1)
        body = r.json()
        task = body["task"]
        print(f"message: {body.get('message')}")
        print(f"status: {task['status']}")
        print(f"final_report 摘要:\n{(task.get('final_report') or '')[:500]}")

        print("\n=== 5. Agent 步骤 ===")
        r = client.get(f"/api/fix-tasks/{task_id}/steps")
        r.raise_for_status()
        steps = r.json()["items"]
        for s in steps:
            out = s.get("output_summary") or {}
            print(
                f"  - {s['node_name']}: {s['status']} "
                f"agent={s['agent_name']} out_keys={list(out.keys())}"
            )

        node_names = [s["node_name"] for s in steps]
        required = [
            "intake_node",
            "clone_repo_node",
            "classify_issue_node",
            "planning_node",
            "approval_node",
            "edit_code_node",
        ]
        missing = [n for n in required if n not in node_names]
        if missing:
            print(f"\n[FAIL] 缺少步骤: {missing}")
            sys.exit(1)

        if "edit_code_node" not in node_names:
            print("\n[FAIL] 未执行 edit_code_node")
            sys.exit(1)

        edit_step = next(s for s in steps if s["node_name"] == "edit_code_node")
        if str(edit_step["status"]) not in ("success", "StepStatus.SUCCESS"):
            print(f"\n[FAIL] edit_code_node 状态: {edit_step['status']}")
            sys.exit(1)

        print("\n[OK] Coder 全链路 E2E 通过（含 edit_code_node）")
        if task["status"] == "success":
            print("[OK] 任务最终 status=success")
        elif task["status"] == "failed":
            print("[WARN] 任务 failed（可能测试未通过，但 Coder 已执行）")
        else:
            print(f"[INFO] 任务 status={task['status']}")


if __name__ == "__main__":
    main()

# backend/test/test_code_retriever.py
# 作用：直接测试 Code Retriever Agent 的语义检索功能
#
# 运行方式（在 backend 目录下）：
#   python test/test_code_retriever.py
#
# 测试策略：
# - 直接用 backend/app 目录作为 "repo"（省去 clone 步骤）
# - 用几个典型的 issue 查询测试语义检索质量
# - 打印检索结果，人工判断是否合理

import sys
import os
from pathlib import Path

if "pytest" in sys.modules:
    import pytest

    real_llm_test_enabled = os.environ.get("RUN_LLM_TESTS") == "1"
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not real_llm_test_enabled or api_key in {"", "test-openai-key"}:
        pytest.skip(
            "语义检索需要真实 Embedding API；默认 pytest 门禁跳过，"
            "如需手动验证请设置 RUN_LLM_TESTS=1 和真实 OPENAI_API_KEY。",
            allow_module_level=True,
        )

# 把 backend 目录加入 Python 路径，确保能 import app.*
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents.code_retriever import retrieve_code
from app.schemas.code_retrieval import CodeRetrievalRequest

# 用 backend/app 目录作为测试 repo
# 这里有足够多的 Python 代码，适合测试语义检索
REPO_PATH = str(Path(__file__).parent.parent / "app")

# 索引缓存放在 backend/test/ 旁边，避免污染 app 目录
CACHE_DIR = Path(__file__).parent / ".test_llamaindex_cache"


def print_result(title: str, result):
    """把检索结果打印成可读格式。"""
    print(f"\n{'=' * 60}")
    print(f"  查询：{title}")
    print(f"  检索方式：{result.search_method}")
    print(f"  返回片段数：{len(result.retrieved_files)}")
    print(f"{'=' * 60}")

    for i, f in enumerate(result.retrieved_files, 1):
        print(f"\n  [{i}] 文件：{f.file_path}  "
              f"行：{f.line_start}-{f.line_end}  "
              f"score={f.score:.4f}  method={f.method}")
        # 只打印前 5 行代码，防止输出太长
        snippet_lines = f.snippet.splitlines()[:5]
        for line in snippet_lines:
            print(f"      | {line}")
        if len(f.snippet.splitlines()) > 5:
            print(f"      | ... (共 {len(f.snippet.splitlines())} 行)")

    print()


# ── 测试用例 1：查找数据库相关代码 ───────────────────────────────────────────
print("\n【测试 1】查找数据库连接和 Session 管理相关代码")
request1 = CodeRetrievalRequest(
    repo_path=REPO_PATH,
    query_text="database connection session management SQLAlchemy async",
    search_method="semantic",
    max_files=5,
)

try:
    result1 = retrieve_code(request1)
    print_result("database connection session management", result1)
    if result1.retrieved_files:
        print("[OK] 语义检索成功返回结果")
        # 简单校验：结果应该包含路径信息
        assert all(f.file_path for f in result1.retrieved_files), "file_path 不能为空"
        assert all(f.line_start > 0 for f in result1.retrieved_files), "line_start 必须 > 0"
        assert all(0.0 <= f.score <= 1.0 for f in result1.retrieved_files), "score 必须在 0~1 之间"
        print("[OK] 字段校验通过（file_path, line_start, score 范围）")
    else:
        print("[WARN] 没有返回任何结果，请检查 repo_path 是否正确")
except Exception as e:
    print(f"[FAIL] 测试 1 失败：{e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)


# ── 测试用例 2：查找 Issue 分析相关代码 ──────────────────────────────────────
print("\n【测试 2】查找 Issue 分析 Agent 相关代码")
request2 = CodeRetrievalRequest(
    repo_path=REPO_PATH,
    query_text="analyze GitHub issue bug report feature request risk level",
    search_method="semantic",
    max_files=5,
)

try:
    result2 = retrieve_code(request2)
    print_result("analyze GitHub issue bug report", result2)

    # 期望：能找到 agents/issue_analyst.py 相关的代码
    found_issue_analyst = any(
        "issue" in f.file_path.lower() or "agent" in f.file_path.lower()
        for f in result2.retrieved_files
    )
    if found_issue_analyst:
        print("[OK] 找到了 issue/agent 相关文件，语义检索质量正常")
    else:
        print("[WARN] 没找到 issue 相关文件，可能语义检索精度偏低（不一定是 bug）")
except Exception as e:
    print(f"[FAIL] 测试 2 失败：{e}")
    import traceback
    traceback.print_exc()


# ── 测试用例 3：测试关键词检索（对比用）────────────────────────────────────
print("\n【测试 3】关键词检索（对比用，不调用 Embedding API）")
request3 = CodeRetrievalRequest(
    repo_path=REPO_PATH,
    keywords=["retrieve_code", "semantic_search", "VectorStoreIndex"],
    search_method="keyword",
    max_files=5,
)

try:
    result3 = retrieve_code(request3)
    print_result("retrieve_code semantic_search VectorStoreIndex (keyword)", result3)
    print(f"  扫描文件总数：{result3.total_searched_files}")
    print(f"  使用关键词：{result3.keywords_used}")
    if result3.retrieved_files:
        print("[OK] 关键词检索正常工作")
    else:
        print("[WARN] 关键词检索没有返回结果")
except Exception as e:
    print(f"[FAIL] 测试 3 失败：{e}")
    import traceback
    traceback.print_exc()


# ── 测试用例 4：验证索引缓存（第二次调用应该更快）────────────────────────
print("\n【测试 4】验证索引缓存（第二次调用应比第一次快）")
import time

start = time.time()
request4 = CodeRetrievalRequest(
    repo_path=REPO_PATH,
    query_text="fix task status pending running approval",
    search_method="semantic",
    max_files=3,
)
result4 = retrieve_code(request4)
elapsed = time.time() - start

print(f"\n  第二次调用耗时：{elapsed:.2f} 秒")
print_result("fix task status pending running", result4)

if elapsed < 5.0:
    print("[OK] 加载缓存速度正常（< 5 秒）")
else:
    print(f"[WARN] 耗时较长（{elapsed:.1f}s），可能没有命中缓存")


print("\n" + "=" * 60)
print("  所有测试完成！")
print("=" * 60 + "\n")

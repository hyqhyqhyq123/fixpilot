# backend/test_issue_analyst.py
# 作用：直接测试 Issue Analyst Agent，不需要启动 FastAPI 服务
#
# 运行方式（在 backend 目录下）：
#   python test_issue_analyst.py

import json
import sys

from app.agents.issue_analyst import analyze_issue
from app.schemas.issue_analysis import IssueAnalysisRequest


def pretty_print(result):
    """把分析结果打印成可读格式。"""
    print("\n" + "=" * 60)
    print(f"  Issue 类型  : {result.issue_type.value}")
    print(f"  风险等级    : {result.risk_level.value}")
    print(f"  需要澄清    : {result.needs_user_clarification}")
    print(f"\n  问题总结    : {result.summary}")
    print(f"\n  期望行为    : {result.expected_behavior}")
    print(f"\n  实际行为    : {result.actual_behavior}")
    print(f"\n  验收条件    :")
    for i, criteria in enumerate(result.acceptance_criteria, 1):
        print(f"    {i}. {criteria}")
    if result.clarification_questions:
        print(f"\n  待澄清问题  :")
        for i, q in enumerate(result.clarification_questions, 1):
            print(f"    {i}. {q}")
    print("=" * 60 + "\n")


# ── 测试用例 1：典型 Bug Report ──────────────────────────────────────
print("\n【测试 1】典型 Bug Report")
request1 = IssueAnalysisRequest(
    issue_text="""
Title: 点击"提交订单"按钮后页面崩溃

Description:
当用户购物车中有超过 10 个商品时，点击"提交订单"按钮后，
页面直接显示 500 Internal Server Error。

错误日志：
KeyError: 'discount_code' at checkout/views.py line 87

Expected behavior:
订单应该正常提交，跳转到支付页面。

Actual behavior:
页面显示 500 错误，订单未创建。

Steps to reproduce:
1. 在购物车添加 11 个以上商品
2. 点击"提交订单"
3. 观察到 500 错误
""",
    repo_context="这是一个 Python Django 电商后端项目，处理用户订单和支付流程。"
)

try:
    result1 = analyze_issue(request1)
    pretty_print(result1)
except Exception as e:
    print(f"测试 1 失败：{e}")
    sys.exit(1)


# ── 测试用例 2：信息不足的 Issue ────────────────────────────────────
print("\n【测试 2】信息不足的 Issue（应该触发 needs_user_clarification=True）")
request2 = IssueAnalysisRequest(
    issue_text="登录有问题，帮我看看",
)

try:
    result2 = analyze_issue(request2)
    pretty_print(result2)
    if result2.needs_user_clarification:
        print("[OK] 正确识别出信息不足，需要用户澄清")
    else:
        print("[FAIL] 应该识别为需要澄清，但没有")
except Exception as e:
    print(f"测试 2 失败：{e}")


# ── 测试用例 3：Feature Request ──────────────────────────────────────
print("\n【测试 3】Feature Request")
request3 = IssueAnalysisRequest(
    issue_text="""
Title: 添加导出 CSV 功能

Description:
用户希望能在报表页面将数据导出为 CSV 格式，
目前只支持 PDF 导出，很多用户反映需要在 Excel 中进行二次处理。

Acceptance Criteria:
- 报表页面出现"导出 CSV"按钮
- 点击后下载包含所有数据的 CSV 文件
- CSV 文件编码为 UTF-8 with BOM（Windows Excel 兼容）
""",
    repo_context="Python FastAPI 后端 + React 前端的数据分析系统"
)

try:
    result3 = analyze_issue(request3)
    pretty_print(result3)
except Exception as e:
    print(f"测试 3 失败：{e}")


print("\n所有测试完成！")

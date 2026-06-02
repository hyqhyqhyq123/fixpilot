# backend/app/agents/planner.py
# 作用：Planner Agent —— 根据 issue 分析结果和代码检索结果，生成修改计划
#
# Planner 的核心职责：
# 1. 理解问题（issue_analysis 给了详细分析）
# 2. 看相关代码（retrieved_files 给了代码片段）
# 3. 生成"修改计划"，说明改哪些文件、为什么改、怎么改
# 4. Planner 只生成计划，绝对不能直接改代码！
#
# 为什么 Planner 不能直接改代码？
# - 代码修改是高风险操作，需要人工审批后才能执行
# - Planner 只负责"想清楚怎么做"，Coder 才负责"真的去做"
# - 分离职责：减少单个 Agent 的权力，降低出错风险

import json
import logging
import re

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from app.core.config import get_settings
from app.schemas.plan import FixPlan, PlannedFileChange
from app.schemas.code_retrieval import CodeRetrievalResult
from app.schemas.issue_analysis import IssueAnalysisResult

logger = logging.getLogger(__name__)

# ── 系统提示词 ────────────────────────────────────────────────────────
SYSTEM_PROMPT = """你是 FixPilot 系统的 Planner Agent，专门根据 issue 分析和相关代码生成修改计划。

你的职责：
1. 深入理解 issue 的根本原因
2. 分析检索到的相关代码片段
3. 制定清晰可执行的修改计划
4. 列出所有需要修改的文件和具体改动

重要限制：
- 你只生成"计划"，不能生成实际代码
- 计划必须具体到文件级别，不能模糊地说"修改相关代码"
- 必须解释为什么改每个文件
- 修改范围要最小化：只改必要的文件

输出要求：
你必须只输出一个合法的 JSON 对象，不要有任何其他文字，格式如下：
{{
  "problem_summary": "1-2句话描述问题本质",
  "root_cause_hypothesis": "基于代码分析的根本原因假设",
  "files_to_modify": [
    {{
      "path": "相对于仓库根目录的文件路径",
      "reason": "为什么要改这个文件",
      "planned_changes": ["具体改动点1", "具体改动点2"],
      "is_new_file": false
    }}
  ],
  "files_to_add": [
    {{
      "path": "新文件路径",
      "reason": "为什么要新建这个文件",
      "planned_changes": ["文件内容描述"],
      "is_new_file": true
    }}
  ],
  "test_plan": ["测试步骤1", "测试步骤2"],
  "risk_analysis": "潜在风险说明",
  "requires_approval": true,
  "estimated_complexity": "low | medium | high（选一个）"
}}

JSON 格式严格要求：
- 所有字段名和字符串值必须用英文双引号
- requires_approval 永远是 true
- 字符串中的双引号必须转义为 \\\"
- 如果没有需要新建的文件，files_to_add 填空数组 []"""


def _build_context_section(
    issue_analysis: dict | None,
    retrieved_result: dict | None,
    repo_analysis: dict | None,
) -> str:
    """
    把 issue 分析、代码检索结果、仓库分析整合成一段上下文文本给 LLM 阅读。

    为什么不直接把原始 dict 传给 LLM？
    - dict 格式对人类不友好，LLM 读起来也容易混乱
    - 格式化成有结构的文本，LLM 更容易理解
    """
    sections = []

    # ── Issue 分析结果 ──
    if issue_analysis:
        sections.append("## Issue 分析结果")
        sections.append(f"- 类型：{issue_analysis.get('issue_type', '未知')}")
        sections.append(f"- 摘要：{issue_analysis.get('summary', '')}")
        sections.append(f"- 期望行为：{issue_analysis.get('expected_behavior', '')}")
        sections.append(f"- 实际行为：{issue_analysis.get('actual_behavior', '')}")
        criteria = issue_analysis.get("acceptance_criteria", [])
        if criteria:
            sections.append("- 验收条件：")
            for c in criteria:
                sections.append(f"  * {c}")
        sections.append(f"- 风险等级：{issue_analysis.get('risk_level', '未知')}")

    # ── 仓库基本信息 ──
    if repo_analysis:
        sections.append("\n## 仓库信息")
        sections.append(
            f"- 检测语言：{', '.join(repo_analysis.get('languages', []))}"
        )
        sections.append(
            f"- 项目类型：{', '.join(repo_analysis.get('project_types', []))}"
        )
        test_cmd = repo_analysis.get("detected_test_command", "")
        if test_cmd:
            sections.append(f"- 测试命令：{test_cmd}")
        # 文件结构摘要（只取前 50 行，避免太长）
        tree = repo_analysis.get("file_tree", "")
        if tree:
            tree_lines = tree.split("\n")[:50]
            sections.append("- 目录结构（部分）：")
            sections.append("```")
            sections.append("\n".join(tree_lines))
            sections.append("```")

    # ── 检索到的相关代码 ──
    if retrieved_result and retrieved_result.get("retrieved_files"):
        sections.append("\n## 检索到的相关代码文件")
        files = retrieved_result["retrieved_files"]
        for i, f in enumerate(files[:8], 1):  # 最多展示 8 个文件
            sections.append(
                f"\n### 文件 {i}：{f.get('file_path', '')} "
                f"（行 {f.get('line_start', 0)}-{f.get('line_end', 0)}）"
            )
            sections.append(f"命中关键词：{', '.join(f.get('matched_keywords', []))}")
            snippet = f.get("snippet", "")
            if snippet:
                sections.append("```")
                # 限制每个片段最多 40 行，避免 prompt 过长
                snippet_lines = snippet.split("\n")[:40]
                sections.append("\n".join(snippet_lines))
                sections.append("```")

    return "\n".join(sections)


def _parse_planner_output(raw_content: str) -> FixPlan:
    """
    解析 LLM 返回的 JSON 为 FixPlan 对象。

    与 issue_analyst.py 里的解析逻辑类似，做两步尝试：
    1. 直接解析
    2. 失败后提取 JSON 块再解析

    参数:
        raw_content: LLM 返回的原始文本

    返回:
        FixPlan 对象

    异常:
        ValueError: 解析失败时
    """
    content = raw_content.strip()

    # 处理 ```json ... ``` 包裹
    if content.startswith("```"):
        lines = content.split("\n")
        end = -1 if lines[-1].strip() == "```" else len(lines)
        content = "\n".join(lines[1:end]).strip()

    # 只取第一个 { 到最后一个 } 之间的内容
    start = content.find("{")
    end = content.rfind("}")
    if start != -1 and end != -1 and end > start:
        content = content[start : end + 1]

    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Planner 返回的内容不是合法 JSON：{e}\n"
            f"原始内容（前500字）：{raw_content[:500]}"
        )

    # ── 把 dict 数据转换成 Pydantic 模型 ──
    try:
        # files_to_modify 里每个元素转成 PlannedFileChange
        files_to_modify = [
            PlannedFileChange(**f) for f in data.get("files_to_modify", [])
        ]
        files_to_add = [
            PlannedFileChange(**f) for f in data.get("files_to_add", [])
        ]

        plan = FixPlan(
            problem_summary=data.get("problem_summary", ""),
            root_cause_hypothesis=data.get("root_cause_hypothesis", ""),
            files_to_modify=files_to_modify,
            files_to_add=files_to_add,
            test_plan=data.get("test_plan", []),
            risk_analysis=data.get("risk_analysis", ""),
            requires_approval=True,  # 永远是 True，不信任 LLM 的值
            estimated_complexity=data.get("estimated_complexity", "medium"),
        )
        return plan
    except Exception as e:
        raise ValueError(f"FixPlan 字段结构不符合预期：{e}\n原始数据：{data}")


def generate_fix_plan(
    issue_text: str,
    issue_analysis: dict | None = None,
    retrieved_result: dict | None = None,
    repo_analysis: dict | None = None,
) -> FixPlan:
    """
    根据 issue 分析结果和相关代码，生成修改计划。

    整体流程：
    1. 把所有上下文整合成一段结构化文本
    2. 让 LLM 阅读后生成 JSON 格式的修改计划
    3. 解析 JSON 为 FixPlan 对象

    参数:
        issue_text: 原始 issue 文本
        issue_analysis: Issue Analyst 的分析结果（dict）
        retrieved_result: Code Retriever 的检索结果（dict）
        repo_analysis: Repo Analyst 的仓库分析结果（dict）

    返回:
        FixPlan：结构化的修改计划

    异常:
        ValueError: LLM 返回内容无法解析时
        Exception: 网络或 API 调用失败时
    """
    logger.info("开始生成修改计划（Planner Agent）")

    settings = get_settings()
    llm = ChatOpenAI(
        model=settings.model_name,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        temperature=0,
    )

    # ── 构建上下文 ──
    context = _build_context_section(issue_analysis, retrieved_result, repo_analysis)

    user_prompt = f"""请根据以下信息，生成修复这个 issue 的代码修改计划。

## 原始 Issue 内容
{issue_text}

{context}

请直接输出 JSON 修改计划，不要有任何其他文字。"""

    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("human", "{user_prompt}"),
    ])

    try:
        messages = prompt.format_messages(user_prompt=user_prompt)
        response = llm.invoke(messages)
        raw_content = response.content
        logger.debug(f"Planner LLM 原始输出：{raw_content[:300]}")

        plan = _parse_planner_output(raw_content)

        logger.info(
            f"修改计划生成完成："
            f"修改文件数={len(plan.files_to_modify)}, "
            f"新建文件数={len(plan.files_to_add)}, "
            f"复杂度={plan.estimated_complexity}"
        )
        return plan

    except ValueError:
        raise
    except Exception as e:
        logger.error(f"Planner Agent 调用失败：{e}")
        raise

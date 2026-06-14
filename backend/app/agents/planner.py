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

from app.core.llm_trace import record_token_usage
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from app.core.config import get_settings
from app.schemas.plan import FixPlan, PlannedFileChange
from app.schemas.code_retrieval import CodeRetrievalResult
from app.schemas.issue_analysis import IssueAnalysisResult
from app.services.prompt_injection_guard import (
    format_prompt_injection_warning,
    sanitize_retrieved_snippet,
)

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
- 对 bug fix，如果仓库已有测试目录，应把新增或更新测试写进 files_to_add / files_to_modify

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
    # project_info 来自 analyze_repo_node（ProjectInfo.model_dump()），
    # 字段名与旧版 repo_analysis 不同，需兼容两种结构。
    if repo_analysis:
        sections.append("\n## 仓库信息")

        primary_lang = repo_analysis.get("primary_language")
        if not primary_lang:
            langs = repo_analysis.get("languages", [])
            primary_lang = ", ".join(langs) if langs else "未知"
        sections.append(f"- 主要语言：{primary_lang}")

        raw_types = repo_analysis.get("project_types", [])
        type_labels: list[str] = []
        for item in raw_types:
            if isinstance(item, dict):
                type_labels.append(item.get("project_type") or item.get("language") or "")
            else:
                type_labels.append(str(item))
        sections.append(f"- 项目类型：{', '.join(t for t in type_labels if t) or '未知'}")

        frameworks = repo_analysis.get("frameworks", [])
        if frameworks:
            sections.append(f"- 框架：{', '.join(frameworks)}")

        test_cmd = (
            repo_analysis.get("test_command")
            or repo_analysis.get("detected_test_command")
            or ""
        )
        if test_cmd:
            sections.append(f"- 测试命令：{test_cmd}")
        # 文件结构摘要（只取前 50 行，避免太长）
        tree = repo_analysis.get("file_tree") or repo_analysis.get("file_tree_summary", "")
        if tree:
            tree_lines = tree.split("\n")[:50]
            sections.append("- 目录结构（部分）：")
            sections.append("```")
            sections.append("\n".join(tree_lines))
            sections.append("```")

    # ── 检索到的相关代码 ──
    if retrieved_result:
        quality = retrieved_result.get("retrieval_quality")
        if quality:
            sections.append("\n## 检索质量评估")
            sections.append(f"- 置信等级：{quality.get('level', 'unknown')}")
            sections.append(f"- 是否足够支撑计划：{quality.get('sufficient', False)}")
            sections.append(f"- 证据片段数：{quality.get('evidence_count', 0)}")
            sections.append(f"- 唯一文件数：{quality.get('unique_file_count', 0)}")
            sections.append(f"- 最高分：{quality.get('top_score', 0)}")
            reasons = quality.get("reasons") or []
            if reasons:
                sections.append("- 原因：")
                for reason in reasons:
                    sections.append(f"  * {reason}")
            if not quality.get("sufficient", False):
                sections.append(
                    "- 规划要求：如果证据不足，必须在风险分析里说明不确定性，"
                    "不要编造未检索到的文件或函数。"
                )

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
                sanitized_snippet, injection_findings = sanitize_retrieved_snippet(snippet)
                warning = format_prompt_injection_warning(
                    f.get("file_path", ""),
                    injection_findings,
                )
                if warning:
                    sections.append(warning)
                sections.append("```")
                # 限制每个片段最多 40 行，避免 prompt 过长
                snippet_lines = sanitized_snippet.split("\n")[:40]
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


TEST_DIR_NAMES = {"tests", "test", "__tests__", "spec"}


def _normalize_repo_path(path: str) -> str:
    return path.replace("\\", "/").strip("/")


def _is_test_path(path: str) -> bool:
    """判断一个仓库相对路径是否像测试文件或测试目录。"""

    normalized = _normalize_repo_path(path)
    parts = normalized.split("/")
    if any(part in TEST_DIR_NAMES for part in parts):
        return True

    filename = parts[-1] if parts else normalized
    return bool(
        filename.startswith("test_")
        or filename.endswith("_test.py")
        or ".test." in filename
        or ".spec." in filename
        or filename.endswith("_test.go")
    )


def _plan_has_test_change(plan: FixPlan) -> bool:
    for item in [*plan.files_to_modify, *plan.files_to_add]:
        if _is_test_path(item.path):
            return True
    return False


def _pick_test_directory(repo_analysis: dict | None) -> str | None:
    """优先使用结构化测试目录；兼容旧 state 中只有文件树文本的情况。"""

    if not repo_analysis:
        return None

    dirs = repo_analysis.get("test_directories") or []
    if dirs:
        return _normalize_repo_path(str(dirs[0]))

    tree = repo_analysis.get("file_tree") or repo_analysis.get("file_tree_summary") or ""
    for dirname in TEST_DIR_NAMES:
        if re.search(rf"(^|\n).*\b{re.escape(dirname)}/", tree):
            return dirname
    return None


def _guess_test_file_path(plan: FixPlan, repo_analysis: dict | None) -> str | None:
    """按常见项目风格推断一个回归测试文件路径。"""

    test_dir = _pick_test_directory(repo_analysis)
    if not test_dir:
        return None

    source_path = ""
    for item in plan.files_to_modify:
        if not _is_test_path(item.path):
            source_path = _normalize_repo_path(item.path)
            break

    filename = source_path.rsplit("/", 1)[-1] if source_path else "fixpilot_regression.py"
    stem = filename.rsplit(".", 1)[0] or "fixpilot_regression"
    primary_type = str((repo_analysis or {}).get("primary_type") or "").lower()

    if source_path.endswith(".ts") or source_path.endswith(".tsx"):
        return f"{test_dir}/{stem}.test.ts"
    if source_path.endswith(".js") or source_path.endswith(".jsx") or primary_type == "nodejs":
        return f"{test_dir}/{stem}.test.js"
    if source_path.endswith(".go") or primary_type == "go":
        return f"{test_dir}/{stem}_test.go"
    if source_path.endswith(".rs") or primary_type == "rust":
        return f"{test_dir}/{stem}_test.rs"
    if source_path.endswith(".java") or "java" in primary_type:
        return f"{test_dir}/{stem}Test.java"
    return f"{test_dir}/test_{stem}.py"


def _ensure_regression_test_in_plan(
    plan: FixPlan,
    issue_analysis: dict | None,
    repo_analysis: dict | None,
) -> FixPlan:
    """
    FR-503 的确定性兜底：bug fix 且仓库有测试目录时，计划里必须出现测试文件。

    LLM 有时会把“补测试”写进自然语言测试计划，却忘记把测试文件放进
    files_to_add / files_to_modify。这里做一个很小的后处理，让 Coder 的白名单
    真正包含测试文件，避免后续因白名单限制而无法补测试。
    """

    if (issue_analysis or {}).get("issue_type") != "bug":
        return plan
    if _plan_has_test_change(plan):
        return plan

    test_path = _guess_test_file_path(plan, repo_analysis)
    if not test_path:
        return plan

    test_change = PlannedFileChange(
        path=test_path,
        reason="为 bug fix 增加回归测试，防止相同问题再次出现",
        planned_changes=[
            "覆盖 issue 描述中的失败场景",
            "断言修复后的期望行为",
        ],
        is_new_file=True,
    )
    test_plan = list(plan.test_plan)
    test_command = (
        (repo_analysis or {}).get("test_command")
        or (repo_analysis or {}).get("detected_test_command")
        or "项目测试命令"
    )
    test_step = f"运行 {test_command}，确认新增回归测试和现有测试通过"
    if not any("回归测试" in item for item in test_plan):
        test_plan.append(test_step)

    return plan.model_copy(
        update={
            "files_to_add": [*plan.files_to_add, test_change],
            "test_plan": test_plan,
        }
    )


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
        record_token_usage(response)
        raw_content = response.content
        logger.debug(f"Planner LLM 原始输出：{raw_content[:300]}")

        plan = _parse_planner_output(raw_content)
        plan = _ensure_regression_test_in_plan(plan, issue_analysis, repo_analysis)

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

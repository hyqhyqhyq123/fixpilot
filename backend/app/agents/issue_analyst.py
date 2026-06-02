# backend/app/agents/issue_analyst.py
# 作用：Issue Analyst Agent —— 分析用户输入的 GitHub Issue
#
# Agent 是什么？
# Agent 是一个能"思考并执行任务"的 AI 程序。
# 这里的 Issue Analyst Agent 不需要调用工具，只需要：
#   1. 接收 issue 文本
#   2. 用 LLM 理解并分析
#   3. 按固定格式输出结构化结果
#
# 为什么用 json_mode 而不是 function calling？
# DeepSeek 思考模式不支持 tool_choice=required（function calling 的底层机制），
# 改用 json_mode：在提示词里告诉 LLM "请输出 JSON"，
# LLM 返回 JSON 字符串后，用 Pydantic 解析成结构化对象。

import json
import logging
import re

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from app.core.config import get_settings
from app.schemas.issue_analysis import IssueAnalysisResult, IssueAnalysisRequest

logger = logging.getLogger(__name__)

# ── 系统提示词（System Prompt）────────────────────────────────────────
# 直接在提示词里写出 JSON 格式要求，让 LLM 明确知道输出什么结构。
# 这比依赖 function calling 机制更兼容不同的 LLM。

SYSTEM_PROMPT = """你是 FixPilot 系统的 Issue Analyst Agent，专门分析 GitHub Issue。

你的职责：
1. 理解 issue 描述的问题
2. 判断 issue 类型（bug/feature/documentation/refactor/test/unknown）
3. 提炼核心问题、期望行为和实际行为
4. 给出清晰可验证的验收条件
5. 评估修复风险等级
6. 判断信息是否足够，如果不够，列出需要澄清的问题

分析原则：
- 保持客观，不要假设没有描述的内容
- 验收条件必须具体可测试，不能模糊
- 风险等级要基于改动范围和影响面来判断
- 如果 issue 信息严重不足（比如只有一句话且缺少复现步骤），设 needs_user_clarification 为 true

语言要求：
- 所有字段内容统一使用中文输出
- 技术名词可以保留英文（如函数名、库名）

输出要求：
你必须只输出一个合法的 JSON 对象，不要有任何其他文字，格式如下：
{{
  "issue_type": "bug | feature | documentation | refactor | test | unknown（选一个）",
  "summary": "1-2句话总结核心问题",
  "expected_behavior": "期望的正确行为",
  "actual_behavior": "实际发生的错误行为",
  "acceptance_criteria": ["验收条件1", "验收条件2"],
  "risk_level": "low | medium | high（选一个）",
  "needs_user_clarification": true 或 false,
  "clarification_questions": ["问题1（仅 needs_user_clarification=true 时填写）"]
}}

JSON 格式严格要求（必须遵守）：
- 所有字段名和字符串值必须用英文双引号包裹
- 字符串内容里如果包含双引号，必须用反斜杠转义：\"
- 不要在字符串中使用未转义的双引号，否则 JSON 无法解析
- 正确示例：{{"summary": "点击\\"提交\\\"按钮后报错"}}
- 错误示例：{{"summary": "点击"提交"按钮后报错"}}"""

# ── 用户消息模板 ──────────────────────────────────────────────────────
USER_PROMPT_TEMPLATE = """请分析以下 GitHub Issue：

## Issue 内容
{issue_text}

{repo_context_section}

请直接输出 JSON，不要有任何其他文字。"""


def _build_repo_context_section(repo_context: str) -> str:
    """
    构建仓库背景信息部分。
    
    为什么单独提取这个函数？
    因为 repo_context 是可选的，有时候没有这个信息，
    我们不想在提示词里出现空的章节让 LLM 困惑。
    """
    if not repo_context.strip():
        return ""
    return f"""## 仓库背景信息
{repo_context}"""


def create_issue_analyst_llm() -> ChatOpenAI:
    """
    创建用于 Issue 分析的 LLM 实例。
    
    temperature=0 的含义：
    - 0 = 确定性输出，每次结果稳定一致（适合结构化分析任务）
    - 1 = 更有创造性，但结果不稳定（适合写文章、头脑风暴）
    """
    settings = get_settings()
    return ChatOpenAI(
        model=settings.model_name,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        temperature=0,
    )


def _extract_json_block(content: str) -> str:
    """
    从 LLM 输出中提取 JSON 部分。
    
    LLM 有时会在 JSON 前后加额外文字或用 ```json``` 包裹，
    这里做防御性处理，只保留 { ... } 的部分。
    """
    content = content.strip()

    # 情况1：```json ... ``` 包裹
    if content.startswith("```"):
        lines = content.split("\n")
        end = -1 if lines[-1].strip() == "```" else len(lines)
        content = "\n".join(lines[1:end]).strip()

    # 情况2：JSON 前后有多余文字，只取第一个 { 到最后一个 } 之间的内容
    start = content.find("{")
    end = content.rfind("}")
    if start != -1 and end != -1 and end > start:
        content = content[start:end + 1]

    return content


def _fix_unescaped_quotes_in_values(json_str: str) -> str:
    """
    修复 JSON 字符串值中未转义的双引号。
    
    为什么需要这个？
    LLM 有时把原始文本里的引号（如"提交订单"）直接放进 JSON 字符串，
    没有转义成 \\\"，导致 JSON 解析失败。
    
    处理策略：
    逐字符扫描，追踪当前是否在 JSON 字符串内，
    遇到"字符串内部的未转义双引号"就替换成 \\\"。
    """
    result = []
    in_string = False      # 当前是否在 JSON 字符串值内部
    i = 0

    while i < len(json_str):
        char = json_str[i]
        prev_char = json_str[i - 1] if i > 0 else ""

        if char == '"' and prev_char != "\\":
            if not in_string:
                # 遇到开引号，进入字符串模式
                in_string = True
                result.append(char)
            else:
                # 在字符串内部遇到双引号
                # 判断：这是合法的结束引号，还是内容里的非法引号？
                # 合法结束引号后面应该是：空白、,、}、]
                rest = json_str[i + 1:].lstrip()
                if rest and rest[0] in (",", "}", "]", "\n", "\r", " ", ""):
                    # 看起来是字符串结束，正常处理
                    in_string = False
                    result.append(char)
                else:
                    # 字符串内部的非法引号，转义它
                    result.append('\\"')
        else:
            result.append(char)

        i += 1

    return "".join(result)


def _parse_llm_json_output(raw_content: str) -> IssueAnalysisResult:
    """
    解析 LLM 返回的 JSON 字符串为 IssueAnalysisResult 对象。
    
    两步防御：
    1. 先尝试直接解析（LLM 输出正确时直接成功）
    2. 失败后尝试修复常见问题（字符串内未转义的引号）再解析
    
    参数:
        raw_content: LLM 返回的原始文本
    
    返回:
        IssueAnalysisResult: 解析后的结构化对象
    
    异常:
        ValueError: 两次尝试都失败时抛出
    """
    content = _extract_json_block(raw_content)

    # 第一次尝试：直接解析
    try:
        data = json.loads(content)
        return IssueAnalysisResult(**data)
    except json.JSONDecodeError:
        pass  # 解析失败，进入修复流程
    except Exception as e:
        raise ValueError(f"JSON 字段不符合预期结构：{e}")

    # 第二次尝试：修复未转义引号后再解析
    logger.warning("JSON 直接解析失败，尝试自动修复未转义引号...")
    fixed_content = _fix_unescaped_quotes_in_values(content)

    try:
        data = json.loads(fixed_content)
        return IssueAnalysisResult(**data)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"LLM 返回的内容不是合法 JSON：{e}\n"
            f"原始内容（前300字）：{raw_content[:300]}"
        )
    except Exception as e:
        raise ValueError(f"JSON 字段不符合预期结构：{e}")


def analyze_issue(request: IssueAnalysisRequest) -> IssueAnalysisResult:
    """
    分析 GitHub Issue，返回结构化分析结果。
    
    整体流程：
    1. 构建提示词（把 issue 文本填入模板）
    2. 调用 LLM，要求输出 JSON
    3. 解析 JSON 为 IssueAnalysisResult 对象
    4. 记录日志，返回结果
    
    参数:
        request: IssueAnalysisRequest，包含 issue_text 和可选的 repo_context
    
    返回:
        IssueAnalysisResult：结构化的分析结果
    
    异常:
        ValueError: 当 LLM 返回内容无法解析为结构化结果时
        Exception: 网络或 API 调用失败时
    """
    logger.info(f"开始分析 issue，文本长度：{len(request.issue_text)} 字符")

    # ── 第 1 步：构建完整的提示词 ──
    repo_context_section = _build_repo_context_section(request.repo_context)

    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("human", USER_PROMPT_TEMPLATE),
    ])

    # ── 第 2 步：创建 LLM ──
    llm = create_issue_analyst_llm()

    try:
        # ── 第 3 步：把变量填入提示词模板，得到真实的消息列表 ──
        messages = prompt.format_messages(
            issue_text=request.issue_text,
            repo_context_section=repo_context_section,
        )

        # ── 第 4 步：把消息发给 LLM，等待回复 ──
        response = llm.invoke(messages)

        # response.content 是 LLM 返回的文本内容
        raw_content = response.content
        logger.debug(f"LLM 原始输出：{raw_content[:300]}")

        # ── 第 5 步：解析 JSON ──
        result = _parse_llm_json_output(raw_content)

        logger.info(
            f"Issue 分析完成："
            f"类型={result.issue_type.value}, "
            f"风险={result.risk_level.value}, "
            f"需要澄清={result.needs_user_clarification}"
        )
        return result

    except ValueError:
        # 解析失败，直接向上抛出
        raise
    except Exception as e:
        logger.error(f"Issue 分析失败：{e}")
        raise

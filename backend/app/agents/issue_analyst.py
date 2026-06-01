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
# with_structured_output 是什么？
# LangChain 提供的功能，它把 Pydantic 类转成 JSON Schema 发给 LLM，
# 要求 LLM 严格按这个 Schema 输出 JSON，然后自动解析成 Pydantic 对象。
# 这样我们就不用自己解析 LLM 的自由文本了。

import logging
from typing import Optional

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from app.core.config import get_settings
from app.schemas.issue_analysis import IssueAnalysisResult, IssueAnalysisRequest

logger = logging.getLogger(__name__)

# ── 系统提示词（System Prompt）────────────────────────────────────────
# 系统提示词告诉 LLM "你是谁、你的职责是什么"。
# 写好系统提示词是让 Agent 输出稳定、准确的关键。

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
- 如果 issue 信息严重不足（比如只有一句话且缺少复现步骤），设 needs_user_clarification=true

语言要求：
- 所有字段内容统一使用中文输出
- 技术名词可以保留英文（如函数名、库名）
"""

# ── 用户消息模板 ──────────────────────────────────────────────────────
# {issue_text} 和 {repo_context} 是占位符，调用时会被实际内容替换

USER_PROMPT_TEMPLATE = """请分析以下 GitHub Issue：

## Issue 内容
{issue_text}

{repo_context_section}

请按照要求的 JSON 格式输出分析结果。"""


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
    
    为什么单独封装成函数？
    - 方便测试时替换（mock）
    - 配置变更只改这一处
    - 可以按需设置不同的 temperature（创造性程度）
    
    temperature=0 的含义：
    - 0 = 确定性输出，每次结果稳定一致（适合结构化分析任务）
    - 1 = 更有创造性，但结果不稳定（适合写文章、头脑风暴）
    """
    settings = get_settings()
    return ChatOpenAI(
        model=settings.model_name,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        temperature=0,  # 结构化输出任务用 0，保证稳定性
    )


def analyze_issue(request: IssueAnalysisRequest) -> IssueAnalysisResult:
    """
    分析 GitHub Issue，返回结构化分析结果。
    
    这是 Issue Analyst Agent 的核心函数，整体流程：
    1. 构建提示词（把 issue 文本填入模板）
    2. 创建 LLM 并绑定输出结构（with_structured_output）
    3. 调用 LLM，自动获得 IssueAnalysisResult 对象
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

    # ChatPromptTemplate 是 LangChain 的提示词模板工具
    # from_messages 接收消息列表，区分 system（系统）和 human（用户）角色
    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("human", USER_PROMPT_TEMPLATE),
    ])

    # ── 第 2 步：创建 LLM 并绑定输出结构 ──
    llm = create_issue_analyst_llm()

    # with_structured_output(IssueAnalysisResult) 做了什么？
    # 1. 把 IssueAnalysisResult 的所有字段和描述转成 JSON Schema
    # 2. 通过 function calling 或 json_mode 发给 LLM
    # 3. LLM 返回的 JSON 自动被解析成 IssueAnalysisResult 实例
    # 这样我们就不需要写任何解析代码！
    structured_llm = llm.with_structured_output(IssueAnalysisResult)

    # ── 第 3 步：组装成 Chain 并调用 ──
    # LangChain 的 | 管道操作符：把 prompt 的输出接到 llm 的输入
    # prompt | structured_llm 等价于：structured_llm.invoke(prompt.format(...))
    chain = prompt | structured_llm

    try:
        result: IssueAnalysisResult = chain.invoke({
            "issue_text": request.issue_text,
            "repo_context_section": repo_context_section,
        })

        logger.info(
            f"Issue 分析完成："
            f"类型={result.issue_type.value}, "
            f"风险={result.risk_level.value}, "
            f"需要澄清={result.needs_user_clarification}"
        )
        return result

    except Exception as e:
        logger.error(f"Issue 分析失败：{e}")
        raise

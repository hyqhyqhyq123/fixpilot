# backend/app/api/routes/code_retrieval.py
# 作用：代码检索相关的 API 接口
#
# 主接口：POST /api/code-retrieval
# - 默认使用语义检索（LlamaIndex + text-embedding-3-small）
# - 也支持关键词检索和混合检索（通过 search_method 字段控制）
#
# 辅助接口：POST /api/code-retrieval/extract-keywords
# - 从 issue 文本提取关键词，用于关键词检索或调试

import logging

from fastapi import APIRouter, HTTPException, status

from app.agents.code_retriever import extract_keywords_from_issue, retrieve_code
from app.schemas.code_retrieval import CodeRetrievalRequest, CodeRetrievalResult

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/code-retrieval", tags=["code-retrieval"])


@router.post(
    "",
    response_model=CodeRetrievalResult,
    summary="检索与 issue 相关的代码文件（支持语义/关键词/混合）",
)
async def search_code(payload: CodeRetrievalRequest) -> CodeRetrievalResult:
    """
    在仓库里检索与 issue 相关的代码文件。

    **语义检索（默认，search_method="semantic"）：**
    - 需要提供 `query_text`（issue 完整文本）或 `issue_summary`
    - 系统自动为 repo 建立向量索引（第一次较慢，后续加载缓存很快）
    - 返回语义最相近的代码 chunk，score 为余弦相似度（0~1）

    **关键词检索（search_method="keyword"）：**
    - 需要提供 `keywords` 列表
    - 直接在文件内容里搜索字符串
    - 不需要 Embedding API，适合调试场景

    **混合检索（search_method="hybrid"）：**
    - 同时运行语义检索和关键词检索，结果合并去重
    - 精度最高，适合复杂 issue

    **前提条件：**
    - 仓库已经 clone 到本地（`repo_path` 必须存在）
    - 语义检索需要 Embedding API 可用（OPENAI_API_KEY 已配置）
    """
    try:
        result = retrieve_code(payload)
        return result
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"代码检索失败：{e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"代码检索失败：{e}",
        )


@router.post(
    "/extract-keywords",
    response_model=list[str],
    summary="从 issue 文本中提取搜索关键词（关键词检索辅助工具）",
)
async def extract_keywords(
    issue_text: str,
    issue_analysis: dict | None = None,
) -> list[str]:
    """
    从 issue 文本中提取关键词。

    主要用于：
    1. 关键词检索模式的关键词准备
    2. 调试关键词提取逻辑

    如果传入 `issue_analysis`（Issue Analyst 的分析结果），
    提取质量会更好（会从 summary 和 acceptance_criteria 里额外提取）。
    """
    try:
        keywords = extract_keywords_from_issue(issue_text, issue_analysis)
        return keywords
    except Exception as e:
        logger.error(f"关键词提取失败：{e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"关键词提取失败：{e}",
        )

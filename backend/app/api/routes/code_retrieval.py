# backend/app/api/routes/code_retrieval.py
# 作用：代码检索相关的 API 接口
#
# 这个接口让前端或测试脚本可以直接触发代码检索，
# 方便调试和验证 Code Retriever Agent 是否正常工作。

import logging

from fastapi import APIRouter, HTTPException, status

from app.agents.code_retriever import extract_keywords_from_issue, retrieve_code
from app.schemas.code_retrieval import CodeRetrievalRequest, CodeRetrievalResult

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/code-retrieval", tags=["code-retrieval"])


@router.post(
    "",
    response_model=CodeRetrievalResult,
    summary="检索与 issue 相关的代码文件",
)
async def search_code(payload: CodeRetrievalRequest) -> CodeRetrievalResult:
    """
    在仓库里用关键词搜索相关代码文件。

    使用前提：
    1. 仓库已经被 clone 到本地（repo_path 必须存在）
    2. 关键词列表不能为空

    返回结果按相关度降序排列，越靠前越相关。
    """
    try:
        result = retrieve_code(payload)
        return result
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"代码检索失败：{e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"代码检索失败：{e}",
        )


@router.post(
    "/extract-keywords",
    response_model=list[str],
    summary="从 issue 文本中提取搜索关键词",
)
async def extract_keywords(
    issue_text: str,
    issue_analysis: dict | None = None,
) -> list[str]:
    """
    从 issue 文本中提取关键词，方便调试关键词提取逻辑。

    issue_analysis 是可选的，如果传入 Issue Analyst 的分析结果，
    提取质量会更好。
    """
    try:
        keywords = extract_keywords_from_issue(issue_text, issue_analysis)
        return keywords
    except Exception as e:
        logger.error(f"关键词提取失败：{e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"关键词提取失败：{e}",
        )

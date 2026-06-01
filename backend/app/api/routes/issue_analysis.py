# backend/app/api/routes/issue_analysis.py
# 作用：Issue 分析相关的 API 路由

import logging

from fastapi import APIRouter, HTTPException

from app.agents.issue_analyst import analyze_issue
from app.schemas.issue_analysis import IssueAnalysisRequest, IssueAnalysisResult

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/issue-analysis", tags=["issue-analysis"])


@router.post(
    "/analyze",
    response_model=IssueAnalysisResult,
    summary="分析 GitHub Issue",
    description="调用 Issue Analyst Agent 分析 issue 文本，返回结构化分析结果。",
)
async def analyze_issue_endpoint(request: IssueAnalysisRequest):
    """
    分析 GitHub Issue。
    
    请求体示例：
    {
        "issue_text": "点击登录按钮后页面报 500 错误，控制台显示 KeyError: 'user_id'",
        "repo_context": "这是一个 Python FastAPI 后端项目"
    }
    
    返回结构化分析结果，包含 issue 类型、风险等级、验收条件等。
    """
    try:
        logger.info(f"收到 issue 分析请求，文本长度：{len(request.issue_text)}")
        result = analyze_issue(request)
        return result

    except ValueError as e:
        # LLM 输出格式不符合预期
        logger.error(f"Issue 分析返回格式异常：{e}")
        raise HTTPException(
            status_code=422,
            detail=f"LLM 输出格式异常，请重试：{str(e)}",
        )

    except Exception as e:
        logger.error(f"Issue 分析失败：{e}")
        raise HTTPException(
            status_code=500,
            detail=f"分析服务暂时不可用：{str(e)}",
        )

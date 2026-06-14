# backend/app/schemas/evaluation.py

from datetime import datetime

from pydantic import BaseModel, Field


class EvaluationRunResponse(BaseModel):
    task_id: int
    overall_score: int
    patch_score: int | None = None
    plan_score: int | None = None
    test_score: int | None = None
    judge_summary: str
    details: dict | None = None
    created_at: datetime


class EvaluationDetailResponse(BaseModel):
    task_id: int
    evaluation: EvaluationRunResponse | None = None

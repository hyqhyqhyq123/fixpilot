# backend/test/test_retrieval_sufficiency.py
# 面试向量化实验：检索证据不足时，系统要能显式提示风险，而不是硬规划。
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents.planner import _build_context_section
from app.graph import nodes
from app.schemas.code_retrieval import CodeRetrievalResult, RetrievedFile
from app.services.retrieval_sufficiency import assess_retrieval_sufficiency


def test_empty_retrieval_is_marked_insufficient():
    quality = assess_retrieval_sufficiency([])

    assert quality.sufficient is False
    assert quality.level == "none"
    assert quality.evidence_count == 0
    assert "检索结果为空或证据数量不足" in quality.reasons
    print("[OK] 空检索结果会被标记为证据不足")


def test_high_score_retrieval_is_marked_sufficient():
    quality = assess_retrieval_sufficiency(
        [
            RetrievedFile(
                file_path="src/validator.py",
                line_start=1,
                line_end=3,
                snippet="def validate_input(value): return value",
                score=0.05,
                method="hybrid",
            )
        ]
    )

    assert quality.sufficient is True
    assert quality.level == "high"
    assert quality.unique_file_count == 1
    print("[OK] 有足够分数和文件命中的检索结果会被标记为可用")


def test_planner_context_warns_when_retrieval_is_insufficient():
    context = _build_context_section(
        issue_analysis={"summary": "unknown issue"},
        repo_analysis=None,
        retrieved_result={
            "retrieved_files": [],
            "retrieval_quality": assess_retrieval_sufficiency([]).model_dump(),
        },
    )

    assert "检索质量评估" in context
    assert "是否足够支撑计划：False" in context
    assert "不要编造未检索到的文件或函数" in context
    print("[OK] Planner context 会提示证据不足和不确定性")


def test_retrieve_context_node_outputs_retrieval_quality():
    def fake_retrieve_code(request):
        return CodeRetrievalResult(
            retrieved_files=[
                RetrievedFile(
                    file_path="src/validator.py",
                    line_start=1,
                    line_end=3,
                    snippet="def validate_input(value): return value",
                    score=0.05,
                    method="hybrid",
                )
            ],
            search_method="hybrid",
        )

    with patch("app.graph.nodes.retrieve_code", fake_retrieve_code):
        updates = nodes.retrieve_context_node(
            {
                "repo_path": "D:/tmp/fake-repo",
                "issue_text": "validate input bug",
                "issue_analysis": {"summary": "validation bug"},
            }
        )

    assert updates["retrieval_quality"]["sufficient"] is True
    assert updates["retrieval_quality"]["level"] == "high"
    print("[OK] retrieve_context_node 会输出 retrieval_quality")


if __name__ == "__main__":
    test_empty_retrieval_is_marked_insufficient()
    test_high_score_retrieval_is_marked_sufficient()
    test_planner_context_warns_when_retrieval_is_insufficient()
    test_retrieve_context_node_outputs_retrieval_quality()

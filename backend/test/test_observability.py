import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.observability import AgentMetrics, HttpMetrics, record_agent_step_metric, setup_observability
from app.models.agent_step import StepStatus


async def test_prometheus_metrics_endpoint_counts_requests():
    app = FastAPI()
    setup_observability(
        app,
        SimpleNamespace(
            enable_prometheus=True,
            enable_opentelemetry=False,
            otel_service_name="fixpilot-test",
            otel_exporter_otlp_endpoint="",
        ),
    )

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/ping")
        assert response.status_code == 200

        metrics = await client.get("/metrics")
        assert metrics.status_code == 200
        body = metrics.text

    assert "fixpilot_http_requests_total" in body
    assert 'method="GET",path="/ping",status="200"' in body
    assert "fixpilot_http_request_duration_seconds_count" in body
    print("[OK] /metrics 输出 Prometheus 请求量和耗时指标")


def test_http_metrics_render_empty_output_is_valid_prometheus_text():
    metrics = HttpMetrics()
    body = metrics.render_prometheus()
    assert "# HELP fixpilot_http_requests_total" in body
    assert "# TYPE fixpilot_http_request_duration_seconds histogram" in body
    print("[OK] 空 metrics 也能输出合法 Prometheus 文本骨架")


def test_opentelemetry_optional_dependency_does_not_break_app():
    app = FastAPI()
    setup_observability(
        app,
        SimpleNamespace(
            enable_prometheus=False,
            enable_opentelemetry=True,
            otel_service_name="fixpilot-test",
            otel_exporter_otlp_endpoint="",
        ),
    )
    assert hasattr(app.state, "opentelemetry_enabled")
    assert app.state.opentelemetry_enabled in {True, False}
    print("[OK] OpenTelemetry 可选启用：依赖缺失时不会影响 FastAPI 启动")


def test_agent_metrics_render_node_latency_status_and_tokens():
    metrics = AgentMetrics()
    metrics.observe_step(
        node_name="planning_node",
        status="success",
        duration_seconds=0.25,
        token_usage={"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140},
    )
    body = metrics.render_prometheus()
    assert 'fixpilot_agent_steps_total{node="planning_node",status="success"} 1' in body
    assert 'fixpilot_agent_step_duration_seconds_sum{node="planning_node"} 0.250000' in body
    assert 'fixpilot_agent_tokens_total{node="planning_node",type="total_tokens"} 140' in body
    print("[OK] Agent metrics 能输出节点状态、耗时和 token")


def test_record_agent_step_metric_accepts_workflow_record():
    started = datetime.now(timezone.utc)
    record_agent_step_metric(
        {
            "node_name": "run_tests_node",
            "status": StepStatus.FAILED,
            "started_at": started,
            "ended_at": started + timedelta(milliseconds=120),
            "output_summary": {},
        }
    )
    print("[OK] workflow_runner step record 可直接写入 Agent metrics")

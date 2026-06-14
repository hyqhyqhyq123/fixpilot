"""FastAPI 可观测性：Prometheus 指标 + OpenTelemetry 可选接入。

可观测性解决的是“线上出问题后怎么定位”的问题：
- metrics：看请求量、状态码、耗时；
- tracing：看一次请求经过哪些内部步骤。
"""

from __future__ import annotations

import logging
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from fastapi import FastAPI, Request, Response

logger = logging.getLogger(__name__)


def _metric_label(value: str) -> str:
    """Prometheus label 里双引号和反斜杠需要转义。"""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return str(path or request.url.path)


@dataclass
class HttpMetrics:
    request_total: Counter[tuple[str, str, int]] = field(default_factory=Counter)
    request_duration_sum: Counter[tuple[str, str]] = field(default_factory=Counter)
    request_duration_count: Counter[tuple[str, str]] = field(default_factory=Counter)
    request_duration_buckets: dict[tuple[str, str], Counter[float]] = field(
        default_factory=lambda: defaultdict(Counter)
    )
    buckets: tuple[float, ...] = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)

    def observe(self, method: str, path: str, status_code: int, duration_seconds: float) -> None:
        key = (method, path)
        self.request_total[(method, path, status_code)] += 1
        self.request_duration_sum[key] += duration_seconds
        self.request_duration_count[key] += 1
        for bucket in self.buckets:
            if duration_seconds <= bucket:
                self.request_duration_buckets[key][bucket] += 1

    def render_prometheus(self) -> str:
        lines = [
            "# HELP fixpilot_http_requests_total Total HTTP requests.",
            "# TYPE fixpilot_http_requests_total counter",
        ]
        for (method, path, status_code), count in sorted(self.request_total.items()):
            lines.append(
                'fixpilot_http_requests_total{method="%s",path="%s",status="%s"} %s'
                % (
                    _metric_label(method),
                    _metric_label(path),
                    status_code,
                    count,
                )
            )

        lines.extend(
            [
                "# HELP fixpilot_http_request_duration_seconds HTTP request duration.",
                "# TYPE fixpilot_http_request_duration_seconds histogram",
            ]
        )
        for method, path in sorted(self.request_duration_count):
            label_base = 'method="%s",path="%s"' % (
                _metric_label(method),
                _metric_label(path),
            )
            cumulative = 0
            bucket_counts = self.request_duration_buckets[(method, path)]
            for bucket in self.buckets:
                cumulative = bucket_counts[bucket]
                lines.append(
                    'fixpilot_http_request_duration_seconds_bucket{%s,le="%s"} %s'
                    % (label_base, bucket, cumulative)
                )
            total_count = self.request_duration_count[(method, path)]
            lines.append(
                'fixpilot_http_request_duration_seconds_bucket{%s,le="+Inf"} %s'
                % (label_base, total_count)
            )
            lines.append(
                "fixpilot_http_request_duration_seconds_sum{%s} %.6f"
                % (label_base, self.request_duration_sum[(method, path)])
            )
            lines.append(
                "fixpilot_http_request_duration_seconds_count{%s} %s"
                % (label_base, total_count)
            )
        return "\n".join(lines) + "\n"


@dataclass
class AgentMetrics:
    step_total: Counter[tuple[str, str]] = field(default_factory=Counter)
    step_duration_sum: Counter[str] = field(default_factory=Counter)
    step_duration_count: Counter[str] = field(default_factory=Counter)
    token_total: Counter[tuple[str, str]] = field(default_factory=Counter)

    def observe_step(
        self,
        node_name: str,
        status: str,
        duration_seconds: float | None,
        token_usage: dict[str, int] | None = None,
    ) -> None:
        self.step_total[(node_name, status)] += 1
        if duration_seconds is not None:
            self.step_duration_sum[node_name] += max(0.0, duration_seconds)
            self.step_duration_count[node_name] += 1
        for token_type, value in (token_usage or {}).items():
            if isinstance(value, int):
                self.token_total[(node_name, token_type)] += value

    def render_prometheus(self) -> str:
        lines = [
            "# HELP fixpilot_agent_steps_total Total LangGraph node executions.",
            "# TYPE fixpilot_agent_steps_total counter",
        ]
        for (node_name, status), count in sorted(self.step_total.items()):
            lines.append(
                'fixpilot_agent_steps_total{node="%s",status="%s"} %s'
                % (_metric_label(node_name), _metric_label(status), count)
            )

        lines.extend(
            [
                "# HELP fixpilot_agent_step_duration_seconds LangGraph node duration.",
                "# TYPE fixpilot_agent_step_duration_seconds summary",
            ]
        )
        for node_name in sorted(self.step_duration_count):
            label = 'node="%s"' % _metric_label(node_name)
            lines.append(
                "fixpilot_agent_step_duration_seconds_sum{%s} %.6f"
                % (label, self.step_duration_sum[node_name])
            )
            lines.append(
                "fixpilot_agent_step_duration_seconds_count{%s} %s"
                % (label, self.step_duration_count[node_name])
            )

        lines.extend(
            [
                "# HELP fixpilot_agent_tokens_total Total LLM tokens by node.",
                "# TYPE fixpilot_agent_tokens_total counter",
            ]
        )
        for (node_name, token_type), count in sorted(self.token_total.items()):
            lines.append(
                'fixpilot_agent_tokens_total{node="%s",type="%s"} %s'
                % (_metric_label(node_name), _metric_label(token_type), count)
            )
        return "\n".join(lines) + "\n"


agent_metrics = AgentMetrics()


def _seconds_between(started_at: datetime | None, ended_at: datetime | None) -> float | None:
    if started_at is None or ended_at is None:
        return None
    return max(0.0, (ended_at - started_at).total_seconds())


def record_agent_step_metric(record: dict) -> None:
    """把 workflow_runner 的 step record 转成 Prometheus 指标。"""
    status = record.get("status")
    status_value = getattr(status, "value", str(status or "unknown"))
    output_summary = record.get("output_summary") or {}
    token_usage = output_summary.get("token_usage") if isinstance(output_summary, dict) else None
    agent_metrics.observe_step(
        node_name=str(record.get("node_name") or "unknown"),
        status=status_value,
        duration_seconds=_seconds_between(record.get("started_at"), record.get("ended_at")),
        token_usage=token_usage if isinstance(token_usage, dict) else None,
    )


def _try_setup_opentelemetry(app: FastAPI, service_name: str, endpoint: str) -> bool:
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except Exception as exc:  # pragma: no cover - depends on optional packages
        logger.warning("OpenTelemetry 未启用：依赖未安装或导入失败：%s", exc)
        return False

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    if endpoint:
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
    return True


def setup_observability(app: FastAPI, settings) -> None:
    """给 FastAPI app 安装 metrics / tracing。

    settings 只要求有 enable_prometheus、enable_opentelemetry 等属性，
    这样测试里可以用简单对象，不需要真的加载 .env。
    """
    metrics = HttpMetrics()
    app.state.http_metrics = metrics
    app.state.agent_metrics = agent_metrics

    if settings.enable_prometheus:

        @app.middleware("http")
        async def http_metrics_middleware(
            request: Request,
            call_next: Callable,
        ) -> Response:
            started = time.perf_counter()
            status_code = 500
            try:
                response = await call_next(request)
                status_code = response.status_code
                return response
            finally:
                metrics.observe(
                    method=request.method,
                    path=_route_template(request),
                    status_code=status_code,
                    duration_seconds=time.perf_counter() - started,
                )

        @app.get("/metrics", include_in_schema=False)
        async def metrics_endpoint() -> Response:
            return Response(
                content=metrics.render_prometheus() + agent_metrics.render_prometheus(),
                media_type="text/plain; version=0.0.4; charset=utf-8",
            )

    app.state.opentelemetry_enabled = False
    if settings.enable_opentelemetry:
        app.state.opentelemetry_enabled = _try_setup_opentelemetry(
            app,
            settings.otel_service_name,
            settings.otel_exporter_otlp_endpoint,
        )

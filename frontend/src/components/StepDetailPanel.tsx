"use client";

import type { AgentStep } from "@/lib/types";
import { formatLocalDateTime } from "@/lib/date";
import {
  formatTokenUsage,
  stepLatencyMs,
} from "@/lib/traceMetrics";

export function StepDetailPanel({ step }: { step: AgentStep | null }) {
  if (!step) {
    return (
      <div className="rounded-lg border border-dashed border-slate-300 p-6 text-sm text-slate-500">
        点击左侧时间线中的节点，查看输入/输出摘要。
      </div>
    );
  }

  const latency = stepLatencyMs(step);
  const relatedFiles = Array.from(new Set(step.related_files ?? []));

  return (
    <div className="space-y-4 rounded-lg border border-slate-200 bg-white p-4">
      <div>
        <h3 className="text-lg font-semibold text-slate-900">{step.agent_name}</h3>
        <p className="font-mono text-sm text-slate-500">{step.node_name}</p>
      </div>

      <div className="grid gap-3 rounded-lg bg-slate-50 p-3 text-sm sm:grid-cols-2">
        <Metric label="状态" value={step.status} />
        <Metric
          label="Latency"
          value={latency != null ? `${latency} ms` : "运行中 / 未结束"}
        />
        <Metric label="Token usage" value={formatTokenUsage(step.token_usage)} />
        <Metric
          label="开始时间"
          value={formatLocalDateTime(step.started_at)}
        />
        {step.ended_at && (
          <Metric
            label="结束时间"
            value={formatLocalDateTime(step.ended_at)}
          />
        )}
      </div>

      {step.error_message && (
        <div className="rounded bg-red-50 p-3 text-sm text-red-800">
          {step.error_message}
        </div>
      )}

      {relatedFiles.length > 0 && (
        <div>
          <h4 className="mb-2 text-sm font-medium text-slate-700">关联文件</h4>
          <ul className="max-h-32 space-y-1 overflow-auto font-mono text-xs text-slate-700">
            {relatedFiles.map((path) => (
              <li key={path} className="rounded bg-slate-100 px-2 py-1">
                {path}
              </li>
            ))}
          </ul>
        </div>
      )}

      <JsonBlock title="输入摘要" data={step.input_summary} />
      <JsonBlock title="输出摘要" data={step.output_summary} />
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
      </p>
      <p className="mt-0.5 text-slate-900">{value}</p>
    </div>
  );
}

function JsonBlock({
  title,
  data,
}: {
  title: string;
  data: Record<string, unknown> | null;
}) {
  return (
    <div>
      <h4 className="mb-1 text-sm font-medium text-slate-700">{title}</h4>
      <pre className="max-h-64 overflow-auto rounded bg-slate-900 p-3 text-xs text-slate-100">
        {data ? JSON.stringify(data, null, 2) : "（无）"}
      </pre>
    </div>
  );
}

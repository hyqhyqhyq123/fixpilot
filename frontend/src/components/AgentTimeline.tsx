"use client";

import type { AgentStep } from "@/lib/types";
import { stepLatencyMs } from "@/lib/traceMetrics";

interface Props {
  steps: AgentStep[];
  selectedId: number | null;
  onSelect: (step: AgentStep) => void;
}

function latencyMs(step: AgentStep): number | null {
  return stepLatencyMs(step);
}

export function AgentTimeline({ steps, selectedId, onSelect }: Props) {
  if (steps.length === 0) {
    return (
      <p className="text-sm text-slate-500">暂无 Agent 步骤，请先启动 Workflow。</p>
    );
  }

  return (
    <ol className="relative space-y-0 border-l border-slate-200 pl-6">
      {steps.map((step) => {
        const ms = latencyMs(step);
        const isSelected = step.id === selectedId;
        const failed = step.status === "failed";

        return (
          <li key={step.id} className="relative pb-6 last:pb-0">
            <span
              className={`absolute -left-[1.35rem] top-1 h-3 w-3 rounded-full border-2 border-white ${
                failed ? "bg-red-500" : "bg-emerald-500"
              }`}
            />
            <button
              type="button"
              onClick={() => onSelect(step)}
              className={`w-full rounded-lg border p-3 text-left transition ${
                isSelected
                  ? "border-blue-500 bg-blue-50"
                  : "border-slate-200 bg-white hover:border-slate-300"
              }`}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-medium text-slate-900">
                  {step.agent_name}
                </span>
                <span className="font-mono text-xs text-slate-500">
                  {step.node_name}
                </span>
              </div>
              <div className="mt-1 flex flex-wrap gap-2 text-xs text-slate-500">
                <span>{step.status}</span>
                {ms != null && <span>{ms} ms</span>}
              </div>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

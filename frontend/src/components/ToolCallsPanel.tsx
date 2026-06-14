"use client";

import type { ToolCallItem } from "@/lib/types";
import { formatLocalDateTime } from "@/lib/date";

interface ToolCallsPanelProps {
  items: ToolCallItem[];
  /** 若指定，只展示该 Agent step 关联的工具调用（Trace 页用） */
  stepId?: number | null;
}

const PERMISSION_STYLE: Record<string, string> = {
  low: "bg-slate-100 text-slate-700",
  medium: "bg-amber-100 text-amber-800",
  high: "bg-red-100 text-red-800",
};

export function ToolCallsPanel({ items, stepId }: ToolCallsPanelProps) {
  const filtered =
    stepId != null ? items.filter((t) => t.step_id === stepId) : items;

  if (filtered.length === 0) {
    return (
      <p className="text-sm text-slate-500">
        {stepId != null ? "该节点暂无工具调用记录" : "暂无工具调用记录"}
      </p>
    );
  }

  return (
    <ul className="space-y-2">
      {filtered.map((call) => (
        <li
          key={call.id}
          className="rounded border border-slate-100 p-3 text-sm"
        >
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono font-medium text-slate-900">
              {call.tool_name}
            </span>
            <span
              className={`rounded px-1.5 py-0.5 text-xs ${PERMISSION_STYLE[call.permission_level] ?? PERMISSION_STYLE.low}`}
            >
              {call.permission_level}
            </span>
            <span
              className={
                call.status === "success"
                  ? "text-emerald-700"
                  : "text-red-700"
              }
            >
              {call.status}
            </span>
            {call.duration_ms != null && (
              <span className="text-xs text-slate-500">
                {call.duration_ms} ms
              </span>
            )}
            <span className="text-xs text-slate-400">
              {formatLocalDateTime(call.created_at)}
            </span>
          </div>
          {(call.input_summary || call.output_summary) && (
            <details className="mt-2">
              <summary className="cursor-pointer text-xs text-blue-600">
                输入 / 输出摘要
              </summary>
              <div className="mt-2 grid gap-2 lg:grid-cols-2">
                {call.input_summary && (
                  <pre className="max-h-32 overflow-auto rounded bg-slate-900 p-2 text-xs text-slate-100">
                    {JSON.stringify(call.input_summary, null, 2)}
                  </pre>
                )}
                {call.output_summary && (
                  <pre className="max-h-32 overflow-auto rounded bg-slate-900 p-2 text-xs text-emerald-100">
                    {JSON.stringify(call.output_summary, null, 2)}
                  </pre>
                )}
              </div>
            </details>
          )}
        </li>
      ))}
    </ul>
  );
}

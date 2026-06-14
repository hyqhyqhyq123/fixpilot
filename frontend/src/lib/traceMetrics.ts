"use client";

import type { AgentStep } from "@/lib/types";

/** 计算节点 latency（优先用 API 字段，否则本地推算） */
export function stepLatencyMs(step: AgentStep): number | null {
  if (step.latency_ms != null) return step.latency_ms;
  if (!step.ended_at) return null;
  return (
    new Date(step.ended_at).getTime() - new Date(step.started_at).getTime()
  );
}

export function formatTokenUsage(
  usage: Record<string, number> | null | undefined,
): string {
  if (!usage) return "暂未记录（非 LLM 节点或未返回 usage）";
  const parts: string[] = [];
  if (usage.prompt_tokens != null) parts.push(`prompt ${usage.prompt_tokens}`);
  if (usage.completion_tokens != null) {
    parts.push(`completion ${usage.completion_tokens}`);
  }
  if (usage.total_tokens != null) parts.push(`total ${usage.total_tokens}`);
  return parts.length > 0 ? parts.join(" · ") : "暂未记录";
}

export function sumStepLatency(steps: AgentStep[]): number {
  return steps.reduce((acc, s) => acc + (stepLatencyMs(s) ?? 0), 0);
}

export function sumTokenUsage(
  steps: AgentStep[],
): Record<string, number> | null {
  let prompt = 0;
  let completion = 0;
  let total = 0;
  let hasAny = false;

  for (const step of steps) {
    const u = step.token_usage;
    if (!u) continue;
    hasAny = true;
    if (u.prompt_tokens != null) prompt += u.prompt_tokens;
    if (u.completion_tokens != null) completion += u.completion_tokens;
    if (u.total_tokens != null) total += u.total_tokens;
  }

  if (!hasAny) return null;
  return {
    prompt_tokens: prompt,
    completion_tokens: completion,
    total_tokens: total,
  };
}

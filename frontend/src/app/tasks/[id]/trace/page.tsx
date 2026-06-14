"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { AgentTimeline } from "@/components/AgentTimeline";
import { StepDetailPanel } from "@/components/StepDetailPanel";
import { ToolCallsPanel } from "@/components/ToolCallsPanel";
import { TraceReplayControls } from "@/components/TraceReplayControls";
import type { AgentStep, FixTask, ToolCallItem } from "@/lib/types";
import { formatTokenUsage, sumStepLatency, sumTokenUsage } from "@/lib/traceMetrics";

export default function TaskTracePage() {
  const params = useParams();
  const taskId = Number(params.id);

  const [task, setTask] = useState<FixTask | null>(null);
  const [steps, setSteps] = useState<AgentStep[]>([]);
  const [toolCalls, setToolCalls] = useState<ToolCallItem[]>([]);
  const [selected, setSelected] = useState<AgentStep | null>(null);
  const [replayIndex, setReplayIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const selectedStepIdRef = useRef<number | null>(null);
  const replayIndexRef = useRef(0);
  const hasLoadedRef = useRef(false);

  const load = useCallback(async () => {
    if (!taskId) return;
    try {
      const [t, s, tc] = await Promise.all([
        api.getTask(taskId),
        api.getSteps(taskId),
        api.getToolCalls(taskId).catch(() => ({ items: [] as ToolCallItem[] })),
      ]);
      setTask(t);
      setSteps(s.items);
      setToolCalls(tc.items ?? []);
      if (s.items.length === 0) {
        replayIndexRef.current = 0;
        selectedStepIdRef.current = null;
        setReplayIndex(0);
        setSelected(null);
        hasLoadedRef.current = true;
        return;
      }

      const selectedId = selectedStepIdRef.current;
      const preservedIndex =
        selectedId == null
          ? -1
          : s.items.findIndex((step) => step.id === selectedId);
      const nextIndex =
        preservedIndex >= 0
          ? preservedIndex
          : hasLoadedRef.current
            ? Math.min(replayIndexRef.current, s.items.length - 1)
            : s.items.length - 1;
      const nextStep = s.items[nextIndex] ?? null;

      replayIndexRef.current = nextIndex;
      selectedStepIdRef.current = nextStep?.id ?? null;
      setReplayIndex(nextIndex);
      setSelected(nextStep);
      hasLoadedRef.current = true;
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    }
  }, [taskId]);

  useEffect(() => {
    load();
    const timer = setInterval(load, 8000);
    return () => clearInterval(timer);
  }, [load]);

  function handleReplayIndexChange(index: number) {
    replayIndexRef.current = index;
    setReplayIndex(index);
    const step = steps[index] ?? null;
    selectedStepIdRef.current = step?.id ?? null;
    setSelected(step);
  }

  return (
    <div>
      <p className="text-sm text-slate-500">
        <Link href={`/tasks/${taskId}`} className="hover:underline">
          ← 任务详情
        </Link>
      </p>
      <h1 className="mt-1 mb-6 text-2xl font-bold text-slate-900">
        Agent Trace — 任务 #{taskId}
      </h1>

      {error && (
        <div className="mb-4 rounded-lg bg-red-50 p-4 text-sm text-red-800">{error}</div>
      )}

      {task && (
        <div className="mb-4 grid gap-2 rounded-lg border border-slate-200 bg-white p-4 text-sm sm:grid-cols-3">
          <p>
            <span className="text-slate-500">状态：</span>
            {task.status} · {task.current_node ?? "—"}
          </p>
          <p>
            <span className="text-slate-500">总 Latency：</span>
            {sumStepLatency(steps)} ms（{steps.length} 步）
          </p>
          <p>
            <span className="text-slate-500">累计 Token：</span>
            {formatTokenUsage(sumTokenUsage(steps))}
          </p>
          <p className="sm:col-span-3 text-xs text-slate-400">
            每 8 秒自动刷新数据，不会打断当前选中的步骤 · 可使用下方回放逐步查看 Agent 执行过程
          </p>
        </div>
      )}

      <TraceReplayControls
        steps={steps}
        currentIndex={replayIndex}
        isPlaying={isPlaying}
        onIndexChange={handleReplayIndexChange}
        onPlayingChange={setIsPlaying}
      />

      <div className="grid gap-6 lg:grid-cols-2">
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <h2 className="mb-4 font-semibold">LangGraph 时间线</h2>
          <AgentTimeline
            steps={steps}
            selectedId={selected?.id ?? null}
            onSelect={(step) => {
              setIsPlaying(false);
              const idx = steps.findIndex((s) => s.id === step.id);
              const nextIndex = idx >= 0 ? idx : 0;
              replayIndexRef.current = nextIndex;
              selectedStepIdRef.current = step.id;
              setReplayIndex(nextIndex);
              setSelected(step);
            }}
          />
        </div>
        <div>
          <h2 className="mb-4 font-semibold">节点详情</h2>
          <StepDetailPanel step={selected} />
          <div className="mt-4 rounded-lg border border-slate-200 bg-white p-4">
            <h3 className="mb-3 text-sm font-semibold text-slate-800">
              该节点工具调用
            </h3>
            <ToolCallsPanel items={toolCalls} stepId={selected?.id ?? null} />
          </div>
        </div>
      </div>
    </div>
  );
}

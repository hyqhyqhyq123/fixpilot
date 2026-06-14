"use client";

import { useCallback, useEffect, useRef } from "react";
import type { AgentStep } from "@/lib/types";
import { stepLatencyMs } from "@/lib/traceMetrics";

interface Props {
  steps: AgentStep[];
  currentIndex: number;
  isPlaying: boolean;
  onIndexChange: (index: number) => void;
  onPlayingChange: (playing: boolean) => void;
}

/** 回放间隔：优先用节点 latency，否则默认 1.2s */
function stepDelayMs(step: AgentStep | undefined): number {
  const ms = step ? stepLatencyMs(step) : null;
  if (ms != null && ms > 0) {
    return Math.min(Math.max(ms, 400), 4000);
  }
  return 1200;
}

export function TraceReplayControls({
  steps,
  currentIndex,
  isPlaying,
  onIndexChange,
  onPlayingChange,
}: Props) {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearTimer = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (!isPlaying || steps.length === 0) {
      clearTimer();
      return;
    }

    if (currentIndex >= steps.length - 1) {
      onPlayingChange(false);
      return;
    }

    const delay = stepDelayMs(steps[currentIndex]);
    timerRef.current = setTimeout(() => {
      onIndexChange(Math.min(currentIndex + 1, steps.length - 1));
    }, delay);

    return clearTimer;
  }, [
    isPlaying,
    currentIndex,
    steps,
    onIndexChange,
    onPlayingChange,
    clearTimer,
  ]);

  if (steps.length === 0) {
    return null;
  }

  const atStart = currentIndex <= 0;
  const atEnd = currentIndex >= steps.length - 1;
  const current = steps[currentIndex];

  return (
    <div className="mb-4 rounded-lg border border-slate-200 bg-white p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-slate-800">任务回放</h2>
        <span className="text-xs text-slate-500">
          步骤 {currentIndex + 1} / {steps.length}
          {current ? ` · ${current.agent_name}` : ""}
        </span>
      </div>

      <input
        type="range"
        min={0}
        max={Math.max(steps.length - 1, 0)}
        value={currentIndex}
        onChange={(e) => {
          onPlayingChange(false);
          onIndexChange(Number(e.target.value));
        }}
        className="mb-3 w-full accent-blue-600"
        aria-label="回放进度"
      />

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={atStart}
          onClick={() => {
            onPlayingChange(false);
            onIndexChange(Math.max(0, currentIndex - 1));
          }}
          className="rounded-md border border-slate-300 px-3 py-1.5 text-sm disabled:opacity-40"
        >
          上一步
        </button>
        <button
          type="button"
          onClick={() => {
            if (isPlaying) {
              onPlayingChange(false);
            } else if (atEnd) {
              onIndexChange(0);
              onPlayingChange(true);
            } else {
              onPlayingChange(true);
            }
          }}
          className="rounded-md bg-blue-600 px-3 py-1.5 text-sm text-white"
        >
          {isPlaying ? "暂停" : atEnd ? "重新播放" : "播放"}
        </button>
        <button
          type="button"
          disabled={atEnd}
          onClick={() => {
            onPlayingChange(false);
            onIndexChange(Math.min(steps.length - 1, currentIndex + 1));
          }}
          className="rounded-md border border-slate-300 px-3 py-1.5 text-sm disabled:opacity-40"
        >
          下一步
        </button>
      </div>
    </div>
  );
}

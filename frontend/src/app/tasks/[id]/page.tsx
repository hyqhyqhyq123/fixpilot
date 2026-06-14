"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { TaskStatusBadge } from "@/components/TaskStatusBadge";
import { AgentTimeline } from "@/components/AgentTimeline";
import { MarkdownView } from "@/components/MarkdownView";
import { ToolCallsPanel } from "@/components/ToolCallsPanel";
import { parseApiDate } from "@/lib/date";
import type {
  AgentStep,
  ApprovalItem,
  FixTask,
  TaskEvaluationResult,
  TaskPrInfo,
  TestRunItem,
  ToolCallItem,
} from "@/lib/types";

const SUMMARY_NODE_ORDER = [
  "intake_node",
  "clone_repo_node",
  "analyze_repo_node",
  "classify_issue_node",
  "retrieve_context_node",
  "planning_node",
  "approval_node",
  "edit_code_node",
  "run_tests_node",
  "review_diff_node",
  "pr_writer_node",
  "final_report_node",
];

function latestStepByNode(steps: AgentStep[], nodeName: string) {
  return steps.filter((step) => step.node_name === nodeName).at(-1);
}

function buildTimelineSummary(steps: AgentStep[]) {
  const latestByNode = new Map<string, AgentStep>();
  for (const step of steps) {
    latestByNode.set(step.node_name, step);
  }

  return Array.from(latestByNode.values()).sort((a, b) => {
    const orderA = SUMMARY_NODE_ORDER.indexOf(a.node_name);
    const orderB = SUMMARY_NODE_ORDER.indexOf(b.node_name);
    const safeOrderA = orderA === -1 ? Number.MAX_SAFE_INTEGER : orderA;
    const safeOrderB = orderB === -1 ? Number.MAX_SAFE_INTEGER : orderB;
    if (safeOrderA !== safeOrderB) return safeOrderA - safeOrderB;
    return parseApiDate(a.started_at).getTime() - parseApiDate(b.started_at).getTime();
  });
}

export default function TaskDetailPage() {
  const params = useParams();
  const taskId = Number(params.id);

  const [task, setTask] = useState<FixTask | null>(null);
  const [steps, setSteps] = useState<AgentStep[]>([]);
  const [diff, setDiff] = useState("");
  const [testRuns, setTestRuns] = useState<TestRunItem[]>([]);
  const [approvals, setApprovals] = useState<ApprovalItem[]>([]);
  const [toolCalls, setToolCalls] = useState<ToolCallItem[]>([]);
  const [prInfo, setPrInfo] = useState<TaskPrInfo | null>(null);
  const [evaluation, setEvaluation] = useState<TaskEvaluationResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [downloadingPatch, setDownloadingPatch] = useState(false);
  const [evaluatingTask, setEvaluatingTask] = useState(false);
  const [planFeedback, setPlanFeedback] = useState("请补充更具体的修改范围");
  const [diffRejectReason, setDiffRejectReason] = useState("请说明为什么拒绝这次 Diff");

  const load = useCallback(async () => {
    if (!taskId) return;
    setError(null);
    try {
      const [t, s, eh, tr, ap, tc, pr, ev] = await Promise.all([
        api.getTask(taskId),
        api.getSteps(taskId).catch(() => ({ items: [] as AgentStep[] })),
        api.getEditHistory(taskId).catch(() => ({ combined_diff: "", items: [] })),
        api.getTestRuns(taskId).catch(() => ({ items: [] as TestRunItem[] })),
        api.getApprovals(taskId).catch(() => ({ items: [] as ApprovalItem[] })),
        api.getToolCalls(taskId).catch(() => ({ items: [] as ToolCallItem[] })),
        api.getTaskGithubPr(taskId).catch(() => null),
        api.getTaskEvaluation(taskId).catch(() => ({ task_id: taskId, evaluation: null })),
      ]);
      setTask(t);
      setSteps(s.items ?? []);
      setDiff(eh.combined_diff ?? "");
      setTestRuns(tr.items ?? []);
      setApprovals(ap.items ?? []);
      setToolCalls(tc.items ?? []);
      setPrInfo(pr);
      setEvaluation(ev.evaluation ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    }
  }, [taskId]);

  const shouldAutoRefresh =
    task?.status === "running" || task?.status === "waiting_approval";

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!shouldAutoRefresh) return;
    const timer = window.setInterval(() => {
      void load();
    }, 3000);
    return () => window.clearInterval(timer);
  }, [load, shouldAutoRefresh]);

  async function startWorkflow() {
    setBusy(true);
    setActionMsg("Workflow 正在启动，页面会自动刷新进度。");
    setError(null);
    // 后端同步执行时，请求可能要等几十秒才返回；先乐观切到 running，方便轮询立即开始。
    setTask((current) =>
      current
        ? {
            ...current,
            status: "running",
            current_agent: current.current_agent ?? "coordinator",
            current_node: current.current_node ?? "start_workflow",
          }
        : current,
    );
    try {
      await api.startWorkflow(taskId);
      setActionMsg("Workflow 已启动，已刷新最新进度。");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "启动失败");
    } finally {
      setBusy(false);
    }
  }

  async function runAction(fn: () => Promise<unknown>, label: string) {
    setBusy(true);
    setActionMsg("操作已提交，正在等待后端执行，页面会自动刷新进度。");
    setError(null);
    try {
      await fn();
      setActionMsg(label);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败");
    } finally {
      setBusy(false);
    }
  }

  const timelineSummarySteps = buildTimelineSummary(steps);
  const hiddenStepCount = Math.max(0, steps.length - timelineSummarySteps.length);
  const planStep = latestStepByNode(steps, "planning_node");
  const planSummary = planStep?.output_summary as Record<string, unknown> | undefined;
  const planApproved = approvals.some(
    (a) => a.approval_type === "PLAN" && a.status === "APPROVED",
  );
  const hasEditStep = steps.some(
    (s) => s.node_name === "edit_code_node" && s.status === "success",
  );
  const isDiffReview =
    task?.status === "waiting_approval" && planApproved && hasEditStep;
  const isPlanReview =
    task?.status === "waiting_approval" && !isDiffReview;
  const canCreatePr =
    !!task &&
    planApproved &&
    diff.length > 0 &&
    (task.status === "success" || isDiffReview) &&
    !prInfo?.pr_url;
  const canEvaluate =
    !!task && (task.status === "success" || task.status === "failed");
  const planFeedbackText = planFeedback.trim();
  const diffRejectReasonText = diffRejectReason.trim();

  async function downloadPatch() {
    setDownloadingPatch(true);
    setActionMsg("正在准备 Patch 下载...");
    setError(null);
    try {
      const patchPayload = await api.getTaskPatch(taskId);
      const patch = patchPayload.patch || diff;
      if (!patch.trim()) {
        throw new Error("当前任务还没有可下载的 Patch");
      }

      const blob = new Blob([patch], { type: "text/x-diff;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `fixpilot-task-${taskId}.patch`;
      // 有些内嵌浏览器会忽略未挂到页面上的 a.click()，所以先挂载再点击。
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setActionMsg("Patch 下载已触发。如果没有弹窗，请查看浏览器下载记录或系统下载目录。");
    } catch (e) {
      setError(e instanceof Error ? e.message : "下载 Patch 失败");
      setActionMsg(null);
    } finally {
      setDownloadingPatch(false);
    }
  }

  async function runEvaluation() {
    setBusy(true);
    setEvaluatingTask(true);
    setActionMsg("LLM 评测正在运行，通常需要几十秒。它只会打分，不会修改代码。");
    setError(null);
    try {
      const result = await api.evaluateTask(taskId);
      setEvaluation(result);
      setActionMsg(`LLM 评测已完成：综合 ${result.overall_score} 分。`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "LLM 评测失败");
      setActionMsg(null);
    } finally {
      setEvaluatingTask(false);
      setBusy(false);
    }
  }

  if (!task && !error) {
    return <p className="text-slate-500">加载任务 #{taskId}…</p>;
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-sm text-slate-500">
            <Link href="/dashboard" className="hover:underline">
              ← 返回列表
            </Link>
          </p>
          <h1 className="mt-1 text-2xl font-bold text-slate-900">任务 #{taskId}</h1>
          {task && (
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <TaskStatusBadge status={task.status} />
              {task.current_agent && (
                <span className="text-sm text-slate-600">
                  {task.current_agent} / {task.current_node}
                </span>
              )}
            </div>
          )}
        </div>
        <Link
          href={`/tasks/${taskId}/trace`}
          className="rounded-md border border-slate-300 px-3 py-2 text-sm hover:bg-white"
        >
          Agent Trace →
        </Link>
      </div>

      {error && (
        <div className="rounded-lg bg-red-50 p-4 text-sm text-red-800">{error}</div>
      )}
      {actionMsg && (
        <div className="rounded-lg bg-emerald-50 p-4 text-sm text-emerald-800">
          {actionMsg}
        </div>
      )}
      {task?.status === "running" && (
        <div className="rounded-lg bg-blue-50 p-4 text-sm text-blue-800">
          Workflow 正在运行，页面会每 3 秒自动刷新一次。
        </div>
      )}
      {isPlanReview && (
        <div className="rounded-lg bg-amber-50 p-4 text-sm text-amber-900">
          Workflow 已生成修改计划，正在等待你审批。确认计划后点击“批准计划”，系统才会继续改代码和跑测试。
        </div>
      )}
      {isDiffReview && (
        <div className="rounded-lg bg-amber-50 p-4 text-sm text-amber-900">
          代码修改已完成，正在等待你审批 Diff。确认后点击“批准 Diff”，系统才会继续生成 PR 文案。
        </div>
      )}

      {task && (
        <>
          <section className="rounded-lg border border-slate-200 bg-white p-4">
            <h2 className="mb-2 font-semibold">仓库 & Issue</h2>
            <p className="text-sm text-blue-600 break-all">{task.repo_url}</p>
            <p className="mt-3 whitespace-pre-wrap text-sm text-slate-700">
              {task.issue_text}
            </p>
          </section>

          <section className="rounded-lg border border-slate-200 bg-white p-4">
            <h2 className="mb-3 font-semibold">操作</h2>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                disabled={busy || task.status !== "pending"}
                onClick={startWorkflow}
                className="rounded-md bg-blue-600 px-3 py-2 text-sm text-white disabled:opacity-40"
              >
                {busy && task.status === "pending"
                  ? "启动中..."
                  : task.status === "pending"
                    ? "启动 Workflow"
                    : "已启动"}
              </button>
              {isPlanReview && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    setTask((current) =>
                      current
                        ? {
                            ...current,
                            status: "running",
                            current_agent: "coordinator",
                            current_node: "approval_node",
                          }
                        : current,
                    );
                    runAction(
                      () => api.approvePlan(taskId, "前端批准"),
                      "计划已批准",
                    );
                  }}
                  className="rounded-md bg-emerald-600 px-3 py-2 text-sm text-white disabled:opacity-40"
                >
                  {busy ? "处理中..." : "批准计划"}
                </button>
              )}
              {isDiffReview && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    runAction(
                      () => api.approveDiff(taskId, "前端批准 diff"),
                      "Diff 已批准，继续生成 PR",
                    )
                  }
                  className="rounded-md bg-emerald-600 px-3 py-2 text-sm text-white disabled:opacity-40"
                >
                  {busy ? "处理中..." : "批准 Diff"}
                </button>
              )}
              {(task.status === "pending" ||
                task.status === "waiting_approval" ||
                task.status === "running") && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    runAction(() => api.cancelTask(taskId), "任务已取消")
                  }
                  className="rounded-md border border-slate-300 px-3 py-2 text-sm hover:bg-slate-50 disabled:opacity-40"
                >
                  取消任务
                </button>
              )}
              {task.status === "failed" && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    setTask((current) =>
                      current
                        ? {
                            ...current,
                            status: "running",
                            current_agent: "coordinator",
                            current_node: "retry_failed_task",
                            error_message: null,
                          }
                        : current,
                    );
                    runAction(
                      () => api.retryTask(taskId, "前端手动重试"),
                      "失败任务已提交重试，页面会自动刷新进度。",
                    );
                  }}
                  className="rounded-md bg-orange-600 px-3 py-2 text-sm text-white disabled:opacity-40"
                >
                  {busy ? "重试中..." : "重试任务"}
                </button>
              )}
              {diff && (
                <button
                  type="button"
                  disabled={busy || downloadingPatch}
                  onClick={downloadPatch}
                  className="rounded-md border border-slate-300 px-3 py-2 text-sm hover:bg-slate-50 disabled:opacity-40"
                >
                  {downloadingPatch ? "准备下载..." : "下载 Patch"}
                </button>
              )}
              {canCreatePr && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    runAction(
                      () => api.createGithubPr(taskId),
                      "Pull Request 已创建（未自动 merge）",
                    )
                  }
                  className="rounded-md bg-violet-600 px-3 py-2 text-sm text-white disabled:opacity-40"
                >
                  创建 GitHub PR
                </button>
              )}
              {canEvaluate && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={runEvaluation}
                  className="rounded-md bg-indigo-600 px-3 py-2 text-sm text-white disabled:opacity-40"
                >
                  {evaluatingTask
                    ? "评测中..."
                    : evaluation
                      ? "重新运行 LLM 评测"
                      : "运行 LLM 评测"}
                </button>
              )}
            </div>
            {canEvaluate && (
              <p className="mt-2 text-xs text-slate-500">
                LLM 评测会让模型阅读 Issue、计划、Diff、测试记录和最终报告，然后给修复质量打分；它不会改代码、提交 PR 或 merge。
              </p>
            )}
            {evaluation && (
              <div className="mt-3 rounded-md bg-indigo-50 p-3 text-sm text-indigo-900">
                <span className="font-medium">最近一次评测：</span>
                综合 {evaluation.overall_score} 分
                {evaluation.patch_score != null && `，Patch ${evaluation.patch_score} 分`}
                {evaluation.test_score != null && `，测试 ${evaluation.test_score} 分`}
              </div>
            )}
            {prInfo?.pr_url && (
              <p className="mt-3 text-sm">
                <span className="text-slate-500">已创建 PR：</span>
                <a
                  href={prInfo.pr_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-600 hover:underline break-all"
                >
                  {prInfo.pr_title ?? prInfo.pr_url}
                </a>
              </p>
            )}
            <p className="mt-2 text-xs text-slate-500">
              创建 PR 需在设置页配置 GitHub Token，且修改计划已批准；系统不会自动 merge。
            </p>
            {isPlanReview && (
              <div className="mt-3 space-y-2">
                <label
                  htmlFor="plan-feedback"
                  className="block text-sm font-medium text-slate-700"
                >
                  补充要求
                </label>
                <div className="flex flex-wrap gap-2">
                  <textarea
                    id="plan-feedback"
                    className="min-h-20 min-w-[240px] flex-1 resize-y rounded border border-slate-300 px-2 py-1 text-sm"
                    value={planFeedback}
                    onChange={(e) => setPlanFeedback(e.target.value)}
                    placeholder="例如：不要修改 API 行为，只补充错误处理"
                  />
                  <button
                    type="button"
                    disabled={busy || !planFeedbackText}
                    onClick={() =>
                      runAction(
                        () => api.rejectPlan(taskId, planFeedbackText),
                        "计划已拒绝并重新规划",
                      )
                    }
                    className="self-start rounded-md bg-amber-600 px-3 py-2 text-sm text-white disabled:opacity-40"
                  >
                    拒绝并重新规划
                  </button>
                </div>
              </div>
            )}
            {isDiffReview && (
              <div className="mt-3 space-y-2">
                <label
                  htmlFor="diff-reject-reason"
                  className="block text-sm font-medium text-slate-700"
                >
                  Diff 拒绝原因
                </label>
                <div className="flex flex-wrap gap-2">
                  <textarea
                    id="diff-reject-reason"
                    className="min-h-20 min-w-[240px] flex-1 resize-y rounded border border-slate-300 px-2 py-1 text-sm"
                    value={diffRejectReason}
                    onChange={(e) => setDiffRejectReason(e.target.value)}
                    placeholder="例如：这次修改影响范围太大，需要缩小到一个文件"
                  />
                  <button
                    type="button"
                    disabled={busy || !diffRejectReasonText}
                    onClick={() =>
                      runAction(
                        () => api.rejectDiff(taskId, diffRejectReasonText),
                        "Diff 已拒绝",
                      )
                    }
                    className="self-start rounded-md bg-amber-600 px-3 py-2 text-sm text-white disabled:opacity-40"
                  >
                    拒绝 Diff
                  </button>
                </div>
              </div>
            )}
          </section>

          {planSummary && (
            <section className="rounded-lg border border-slate-200 bg-white p-4">
              <h2 className="mb-2 font-semibold">修改计划摘要</h2>
              <pre className="overflow-auto rounded bg-slate-900 p-3 text-xs text-slate-100">
                {JSON.stringify(planSummary, null, 2)}
              </pre>
            </section>
          )}

          <section className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-lg border border-slate-200 bg-white p-4">
              <h2 className="mb-3 font-semibold">Agent 时间线（摘要）</h2>
              {hiddenStepCount > 0 && (
                <p className="mb-3 text-xs text-slate-500">
                  已折叠 {hiddenStepCount} 条重复或历史步骤；完整记录请查看 Agent Trace。
                </p>
              )}
              <AgentTimeline
                steps={timelineSummarySteps}
                selectedId={null}
                onSelect={() => {}}
              />
            </div>
            <div className="rounded-lg border border-slate-200 bg-white p-4">
              <h2 className="mb-2 font-semibold">审批记录</h2>
              {approvals.length === 0 ? (
                <p className="text-sm text-slate-500">暂无</p>
              ) : (
                <ul className="space-y-2 text-sm">
                  {approvals.map((a) => (
                    <li key={a.id} className="rounded border border-slate-100 p-2">
                      <span className="font-medium">{a.status}</span> — {a.approval_type}
                      {a.user_comment && (
                        <p className="text-slate-600">{a.user_comment}</p>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>

          <section className="rounded-lg border border-slate-200 bg-white p-4">
            <h2 className="mb-3 font-semibold">工具调用记录</h2>
            <ToolCallsPanel items={toolCalls} />
          </section>

          <section className="rounded-lg border border-slate-200 bg-white p-4">
            <h2 className="mb-2 font-semibold">Diff</h2>
            <pre className="max-h-80 overflow-auto rounded bg-slate-900 p-3 text-xs text-emerald-100">
              {diff || "（尚无代码修改）"}
            </pre>
          </section>

          <section className="rounded-lg border border-slate-200 bg-white p-4">
            <h2 className="mb-2 font-semibold">测试日志</h2>
            {testRuns.length === 0 ? (
              <p className="text-sm text-slate-500">暂无测试记录</p>
            ) : (
              <div className="space-y-3">
                {testRuns.map((run) => (
                  <div key={run.id} className="rounded border border-slate-100 p-3 text-sm">
                    <div className="flex flex-wrap gap-2">
                      <span className={run.passed ? "text-emerald-700" : "text-red-700"}>
                        {run.passed ? "通过" : "失败"}
                      </span>
                      <code className="text-xs">{run.command}</code>
                      <span className="text-slate-500">retry={run.retry_index}</span>
                    </div>
                    {run.stderr && (
                      <pre className="mt-2 max-h-32 overflow-auto rounded bg-slate-900 p-2 text-xs text-red-200">
                        {run.stderr.slice(0, 2000)}
                      </pre>
                    )}
                  </div>
                ))}
              </div>
            )}
          </section>

          {evaluation && (
            <section className="rounded-lg border border-slate-200 bg-white p-4">
              <h2 className="mb-2 font-semibold">LLM-as-Judge 评测</h2>
              <div className="grid gap-2 text-sm sm:grid-cols-4">
                <p>
                  <span className="text-slate-500">综合：</span>
                  <span className="font-semibold text-indigo-700">
                    {evaluation.overall_score}
                  </span>
                </p>
                <p>
                  <span className="text-slate-500">Patch：</span>
                  {evaluation.patch_score ?? "—"}
                </p>
                <p>
                  <span className="text-slate-500">计划：</span>
                  {evaluation.plan_score ?? "—"}
                </p>
                <p>
                  <span className="text-slate-500">测试：</span>
                  {evaluation.test_score ?? "—"}
                </p>
              </div>
              <p className="mt-3 text-sm text-slate-700">{evaluation.judge_summary}</p>
            </section>
          )}

          {task.final_report && (
            <section className="rounded-lg border border-slate-200 bg-white p-4">
              <h2 className="mb-2 font-semibold">最终报告</h2>
              <MarkdownView content={task.final_report} />
            </section>
          )}
        </>
      )}
    </div>
  );
}

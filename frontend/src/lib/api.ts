/**
 * FixPilot API 客户端
 * 所有请求指向 FastAPI 后端。
 * 本地开发如果端口不同，请用 frontend/.env.local 的 NEXT_PUBLIC_API_URL 覆盖。
 */

import type {
  AgentStep,
  ApprovalItem,
  AuthUser,
  EditHistoryItem,
  CreatePrResponse,
  FixTask,
  FixTaskCreatePayload,
  FixTaskListResponse,
  GitHubIssueInfo,
  GitHubOAuthStartResponse,
  PatchResponse,
  TaskEvaluationResponse,
  TaskEvaluationResult,
  TestRunItem,
  TaskPrInfo,
  TokenResponse,
  ToolCallItem,
  UserSettings,
  UserSettingsUpdatePayload,
} from "./types";
import { getAccessToken } from "./auth";

const DEFAULT_API_BASE = "http://127.0.0.1:8001";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") || DEFAULT_API_BASE;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getAccessToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string> | undefined),
  };
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
    cache: "no-store",
  });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      /* ignore */
    }
    throw new Error(`${res.status}: ${detail}`);
  }

  if (res.status === 204) {
    return undefined as T;
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => request<{ status: string }>("/health"),

  register: (email: string, password: string) =>
    request<AuthUser>("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  login: (email: string, password: string) =>
    request<TokenResponse>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  startGithubOAuth: () =>
    request<GitHubOAuthStartResponse>("/api/auth/github/authorize"),

  completeGithubOAuth: (code: string, state: string) =>
    request<TokenResponse>("/api/auth/github/callback", {
      method: "POST",
      body: JSON.stringify({ code, state }),
    }),

  logout: () =>
    request<{ message: string }>("/api/auth/logout", { method: "POST" }),

  getMe: () => request<AuthUser>("/api/auth/me"),

  getSettings: () => request<UserSettings>("/api/settings"),

  updateSettings: (payload: UserSettingsUpdatePayload) =>
    request<UserSettings>("/api/settings", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  listTasks: (page = 1, pageSize = 20) =>
    request<FixTaskListResponse>(
      `/api/fix-tasks?page=${page}&page_size=${pageSize}`,
    ),

  getTask: (id: number) => request<FixTask>(`/api/fix-tasks/${id}`),

  createTask: (payload: FixTaskCreatePayload) =>
    request<FixTask>("/api/fix-tasks", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  startWorkflow: (id: number) =>
    request<{ message: string; task: FixTask }>(
      `/api/fix-tasks/${id}/start`,
      { method: "POST" },
    ),

  approvePlan: (id: number, comment?: string) =>
    request<{ message: string; task: FixTask }>(
      `/api/fix-tasks/${id}/approve`,
      {
        method: "POST",
        body: JSON.stringify({ comment: comment ?? null }),
      },
    ),

  rejectPlan: (id: number, reason: string) =>
    request<{ message: string; task: FixTask }>(
      `/api/fix-tasks/${id}/reject`,
      {
        method: "POST",
        body: JSON.stringify({ reason }),
      },
    ),

  approveDiff: (id: number, comment?: string) =>
    request<{ message: string; task: FixTask }>(
      `/api/fix-tasks/${id}/approve-diff`,
      {
        method: "POST",
        body: JSON.stringify({ comment: comment ?? null }),
      },
    ),

  rejectDiff: (id: number, reason: string) =>
    request<{ message: string; task: FixTask }>(
      `/api/fix-tasks/${id}/reject-diff`,
      {
        method: "POST",
        body: JSON.stringify({ reason }),
      },
    ),

  cancelTask: (id: number) =>
    request<{ message: string; task: FixTask }>(
      `/api/fix-tasks/${id}/cancel`,
      { method: "POST" },
    ),

  retryTask: (id: number, comment?: string) =>
    request<{ message: string; task: FixTask }>(
      `/api/fix-tasks/${id}/retry`,
      {
        method: "POST",
        body: JSON.stringify({ comment: comment ?? null }),
      },
    ),

  getSteps: (id: number) =>
    request<{ task_id: number; items: AgentStep[]; total: number }>(
      `/api/fix-tasks/${id}/steps`,
    ),

  getEditHistory: (id: number) =>
    request<{
      task_id: number;
      items: EditHistoryItem[];
      total: number;
      combined_diff: string;
    }>(`/api/fix-tasks/${id}/edit-history`),

  getTestRuns: (id: number) =>
    request<{ task_id: number; items: TestRunItem[]; total: number }>(
      `/api/fix-tasks/${id}/test-runs`,
    ),

  getApprovals: (id: number) =>
    request<{ task_id: number; items: ApprovalItem[]; total: number }>(
      `/api/fix-tasks/${id}/approvals`,
    ),

  getToolCalls: (id: number) =>
    request<{ task_id: number; items: ToolCallItem[]; total: number }>(
      `/api/fix-tasks/${id}/tool-calls`,
    ),

  getTaskPatch: (id: number) =>
    request<PatchResponse>(`/api/fix-tasks/${id}/patch`),

  getTaskGithubPr: (id: number) =>
    request<TaskPrInfo>(`/api/fix-tasks/${id}/github-pr`),

  createGithubPr: (id: number) =>
    request<CreatePrResponse>(`/api/fix-tasks/${id}/create-pr`, {
      method: "POST",
      body: JSON.stringify({ confirm: true }),
    }),

  fetchGithubIssue: (issueUrl: string) =>
    request<GitHubIssueInfo>(
      `/api/github/issues?url=${encodeURIComponent(issueUrl)}`,
    ),

  evaluateTask: (id: number) =>
    request<TaskEvaluationResult>(`/api/fix-tasks/${id}/evaluate`, {
      method: "POST",
    }),

  getTaskEvaluation: (id: number) =>
    request<TaskEvaluationResponse>(`/api/fix-tasks/${id}/evaluation`),
};

export { API_BASE };

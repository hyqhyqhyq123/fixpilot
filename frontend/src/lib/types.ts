/**
 * FixPilot 后端 API 类型（与 backend/app/schemas 对齐）
 */

export type TaskStatus =
  | "pending"
  | "running"
  | "waiting_approval"
  | "success"
  | "failed"
  | "cancelled";

export interface FixTask {
  id: number;
  repo_url: string;
  issue_url: string | null;
  issue_text: string;
  base_branch: string;
  test_command: string | null;
  lint_command: string | null;
  status: TaskStatus;
  current_agent: string | null;
  current_node: string | null;
  retry_count: number;
  max_retries: number;
  workspace_path: string | null;
  final_report: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface FixTaskListResponse {
  items: FixTask[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface AgentStep {
  id: number;
  task_id: number;
  agent_name: string;
  node_name: string;
  status: string;
  input_summary: Record<string, unknown> | null;
  output_summary: Record<string, unknown> | null;
  error_message: string | null;
  started_at: string;
  ended_at: string | null;
  /** API 计算字段：节点耗时 ms */
  latency_ms?: number | null;
  /** API 计算字段：LLM token 用量 */
  token_usage?: Record<string, number> | null;
  /** API 计算字段：关联文件路径 */
  related_files?: string[];
}

export interface EditHistoryItem {
  id: number;
  task_id: number;
  retry_index: number;
  file_path: string;
  diff: string | null;
  created_at: string;
}

export interface TestRunItem {
  id: number;
  task_id: number;
  retry_index: number;
  command: string;
  exit_code: number;
  stdout: string | null;
  stderr: string | null;
  duration_ms: number | null;
  passed: boolean;
  created_at: string;
}

export interface ApprovalItem {
  id: number;
  task_id: number;
  approval_type: string;
  status: string;
  user_comment: string | null;
  created_at: string;
}

export interface ToolCallItem {
  id: number;
  task_id: number;
  step_id: number | null;
  tool_name: string;
  permission_level: string;
  input_summary: Record<string, unknown> | null;
  output_summary: Record<string, unknown> | null;
  status: string;
  duration_ms: number | null;
  created_at: string;
}

export interface FixTaskCreatePayload {
  repo_url: string;
  issue_text: string;
  issue_url?: string;
  base_branch?: string;
  test_command?: string;
  lint_command?: string;
  max_retries?: number;
}

export interface AuthUser {
  id: number;
  email: string;
  github_user_id: string | null;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: AuthUser;
}

export interface GitHubOAuthStartResponse {
  auth_url: string;
  state: string;
}

export interface UserSettings {
  github_token_configured: boolean;
  github_token_hint: string | null;
  model_name: string;
  llm_base_url: string;
  user_model_name: string | null;
  user_llm_base_url: string | null;
  server_model_name: string;
  server_llm_base_url: string;
}

export interface UserSettingsUpdatePayload {
  github_token?: string | null;
  model_name?: string | null;
  llm_base_url?: string | null;
}

export interface TaskPrInfo {
  task_id: number;
  pr_url: string | null;
  branch_name: string | null;
  pr_title: string | null;
  created_at: string | null;
}

export interface CreatePrResponse {
  task_id: number;
  pr_url: string;
  branch_name: string;
  pr_title: string;
  message: string;
}

export interface PatchResponse {
  task_id: number;
  patch: string;
}

export interface GitHubIssueInfo {
  owner: string;
  repo: string;
  number: number;
  title: string;
  body: string;
  issue_text: string;
  state: string | null;
  html_url: string;
  labels: string[];
}

export interface TaskEvaluationResult {
  task_id: number;
  overall_score: number;
  patch_score: number | null;
  plan_score: number | null;
  test_score: number | null;
  judge_summary: string;
  details: Record<string, unknown> | null;
  created_at: string;
}

export interface TaskEvaluationResponse {
  task_id: number;
  evaluation: TaskEvaluationResult | null;
}

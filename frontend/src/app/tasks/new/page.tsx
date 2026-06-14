"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { api } from "@/lib/api";

export default function NewTaskPage() {
  const router = useRouter();
  const [repoUrl, setRepoUrl] = useState("");
  const [issueUrl, setIssueUrl] = useState("");
  const [issueText, setIssueText] = useState("");
  const [testCommand, setTestCommand] = useState("");
  const [loading, setLoading] = useState(false);
  const [fetchingIssue, setFetchingIssue] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function friendlyError(err: unknown, fallback: string) {
    const message = err instanceof Error ? err.message : fallback;
    if (message.includes("rate limit") || message.includes("已限流")) {
      return (
        "GitHub API 已限流。请先登录，并在设置页配置 GitHub Token 后重试；" +
        "也可以临时手动粘贴 Issue 描述。"
      );
    }
    return message;
  }

  async function fetchIssueFromGitHub() {
    if (!issueUrl.trim()) {
      setError("请先填写 GitHub Issue URL");
      return null;
    }
    setFetchingIssue(true);
    setError(null);
    try {
      const issue = await api.fetchGithubIssue(issueUrl.trim());
      setIssueText(issue.issue_text);
      if (!repoUrl.includes(issue.repo)) {
        setRepoUrl(`https://github.com/${issue.owner}/${issue.repo}`);
      }
      return issue;
    } catch (err) {
      setError(friendlyError(err, "拉取 Issue 失败"));
      return null;
    } finally {
      setFetchingIssue(false);
    }
  }

  async function onFetchIssue() {
    await fetchIssueFromGitHub();
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      let resolvedIssueText = issueText.trim();
      let resolvedRepoUrl = repoUrl.trim();
      const resolvedIssueUrl = issueUrl.trim();

      if (!resolvedIssueUrl) {
        throw new Error("请填写 GitHub Issue URL");
      }

      if (!resolvedIssueText || !resolvedRepoUrl) {
        const issue = await fetchIssueFromGitHub();
        if (!issue) {
          throw new Error("无法自动读取 GitHub Issue，请先点击拉取或手动填写 Issue 描述");
        }
        resolvedIssueText = resolvedIssueText || issue.issue_text;
        resolvedRepoUrl = resolvedRepoUrl || `https://github.com/${issue.owner}/${issue.repo}`;
      }

      if (!resolvedRepoUrl) {
        throw new Error("请填写 GitHub 仓库 URL，或填写 GitHub Issue URL 让系统自动识别仓库");
      }

      if (!resolvedIssueText) {
        throw new Error("请填写 Issue 描述，或填写 GitHub Issue URL 让系统自动读取");
      }

      const task = await api.createTask({
        repo_url: resolvedRepoUrl,
        issue_text: resolvedIssueText,
        issue_url: resolvedIssueUrl || undefined,
        test_command: testCommand || undefined,
      });
      router.push(`/tasks/${task.id}`);
    } catch (err) {
      setError(friendlyError(err, "创建失败"));
    } finally {
      setLoading(false);
    }
  }

  const hasIssueUrl = !!issueUrl.trim();

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="mb-6 text-2xl font-bold text-slate-900">新建修复任务</h1>

      <form onSubmit={onSubmit} className="space-y-4 rounded-lg border border-slate-200 bg-white p-6">
        <label className="block text-sm">
          <span className="font-medium text-slate-700">GitHub Issue URL</span>
          <div className="mt-1 flex flex-col gap-2 sm:flex-row">
            <input
              required
              className="w-full rounded-md border border-slate-300 px-3 py-2"
              placeholder="https://github.com/owner/repo/issues/123"
              value={issueUrl}
              onChange={(e) => setIssueUrl(e.target.value)}
            />
            <button
              type="button"
              disabled={fetchingIssue}
              onClick={onFetchIssue}
              className="w-full shrink-0 rounded-md border border-slate-300 px-3 py-2 text-sm hover:bg-slate-50 disabled:opacity-50 sm:w-auto"
            >
              {fetchingIssue ? "拉取中…" : "从 GitHub 拉取"}
            </button>
          </div>
        </label>

        <label className="block text-sm">
          <span className="font-medium text-slate-700">GitHub 仓库 URL</span>
          <span className="ml-2 text-xs text-slate-500">
            可选，留空则创建时会从 Issue URL 自动识别
          </span>
          <input
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2"
            placeholder="https://github.com/owner/repo"
            value={repoUrl}
            onChange={(e) => setRepoUrl(e.target.value)}
          />
        </label>

        <label className="block text-sm">
          <span className="font-medium text-slate-700">Issue 描述</span>
          <span className="ml-2 text-xs text-slate-500">
            可选，留空则创建时会自动读取 Issue URL
          </span>
          <textarea
            minLength={10}
            rows={6}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2"
            value={issueText}
            onChange={(e) => setIssueText(e.target.value)}
          />
        </label>

        <label className="block text-sm">
          <span className="font-medium text-slate-700">测试命令（可选）</span>
          <input
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2"
            placeholder="留空则由 Agent 自动检测，如 pytest"
            value={testCommand}
            onChange={(e) => setTestCommand(e.target.value)}
          />
        </label>

        {error && (
          <div className="rounded bg-red-50 p-3 text-sm text-red-800">{error}</div>
        )}

        <button
          type="submit"
          disabled={loading || fetchingIssue}
          className="rounded-md bg-blue-600 px-4 py-2 text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {loading && hasIssueUrl && (!issueText.trim() || !repoUrl.trim())
            ? "拉取并创建中…"
            : loading
              ? "创建中…"
              : "创建任务"}
        </button>
      </form>
    </div>
  );
}

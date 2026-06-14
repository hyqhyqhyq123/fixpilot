"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";
import type { UserSettings } from "@/lib/types";

export default function SettingsPage() {
  const router = useRouter();
  const [settings, setSettings] = useState<UserSettings | null>(null);
  const [githubToken, setGithubToken] = useState("");
  const [modelName, setModelName] = useState("");
  const [llmBaseUrl, setLlmBaseUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!getAccessToken()) {
      router.replace("/login");
      return;
    }
    setError(null);
    try {
      const s = await api.getSettings();
      setSettings(s);
      setModelName(s.user_model_name ?? s.server_model_name);
      setLlmBaseUrl(s.user_llm_base_url ?? s.server_llm_base_url);
      setGithubToken("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    }
  }, [router]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setMsg(null);
    try {
      const payload: {
        model_name: string;
        llm_base_url: string;
        github_token?: string;
      } = {
        model_name: modelName.trim(),
        llm_base_url: llmBaseUrl.trim(),
      };
      if (githubToken.trim()) {
        payload.github_token = githubToken.trim();
      }
      const updated = await api.updateSettings(payload);
      setSettings(updated);
      setGithubToken("");
      setMsg("设置已保存");
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败");
    } finally {
      setBusy(false);
    }
  }

  async function clearToken() {
    setBusy(true);
    setError(null);
    try {
      const updated = await api.updateSettings({ github_token: "" });
      setSettings(updated);
      setGithubToken("");
      setMsg("GitHub Token 已清除");
    } catch (err) {
      setError(err instanceof Error ? err.message : "清除失败");
    } finally {
      setBusy(false);
    }
  }

  if (!settings && !error) {
    return <p className="text-slate-500">加载设置…</p>;
  }

  return (
    <div className="mx-auto max-w-lg">
      <p className="text-sm text-slate-500">
        <Link href="/dashboard" className="hover:underline">
          ← 返回列表
        </Link>
      </p>
      <h1 className="mt-1 mb-6 text-2xl font-bold text-slate-900">设置</h1>

      {error && (
        <div className="mb-4 rounded-lg bg-red-50 p-3 text-sm text-red-800">
          {error}
        </div>
      )}
      {msg && (
        <div className="mb-4 rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800">
          {msg}
        </div>
      )}

      {settings && (
        <form
          onSubmit={handleSave}
          className="space-y-4 rounded-lg border border-slate-200 bg-white p-6"
        >
          <section>
            <h2 className="mb-2 font-semibold">GitHub Token</h2>
            <p className="mb-2 text-xs text-slate-500">
              用于后续 GitHub 集成（创建 PR 等）。不会在前端显示完整 Token。
            </p>
            {settings.github_token_configured && (
              <p className="mb-2 text-sm text-emerald-700">
                已配置：{settings.github_token_hint}
              </p>
            )}
            <input
              type="password"
              placeholder="输入新的 Personal Access Token"
              value={githubToken}
              onChange={(e) => setGithubToken(e.target.value)}
              className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
              autoComplete="off"
            />
            {settings.github_token_configured && (
              <button
                type="button"
                disabled={busy}
                onClick={clearToken}
                className="mt-2 text-sm text-red-600 hover:underline"
              >
                清除已保存的 Token
              </button>
            )}
          </section>

          <section>
            <h2 className="mb-2 font-semibold">模型配置</h2>
            <p className="mb-2 text-xs text-slate-500">
              留空则使用服务器默认（当前默认：{settings.server_model_name}）
            </p>
            <label className="mb-3 block text-sm">
              <span className="font-medium text-slate-700">模型名称</span>
              <input
                value={modelName}
                onChange={(e) => setModelName(e.target.value)}
                className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
              />
            </label>
            <label className="block text-sm">
              <span className="font-medium text-slate-700">LLM Base URL</span>
              <input
                value={llmBaseUrl}
                onChange={(e) => setLlmBaseUrl(e.target.value)}
                className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
              />
            </label>
          </section>

          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-md bg-blue-600 py-2 text-white disabled:opacity-50"
          >
            {busy ? "保存中…" : "保存设置"}
          </button>
        </form>
      )}
    </div>
  );
}

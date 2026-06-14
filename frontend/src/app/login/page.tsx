"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { setAccessToken } from "@/lib/auth";

type Mode = "login" | "register";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const state = params.get("state");
    if (!code || !state) return;
    const oauthCode = code;
    const oauthState = state;

    let cancelled = false;
    async function completeOAuth() {
      setBusy(true);
      setError(null);
      try {
        const data = await api.completeGithubOAuth(oauthCode, oauthState);
        if (cancelled) return;
        setAccessToken(data.access_token);
        router.push("/dashboard");
        router.refresh();
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "GitHub 登录失败");
        }
      } finally {
        if (!cancelled) {
          setBusy(false);
        }
      }
    }

    void completeOAuth();
    return () => {
      cancelled = true;
    };
  }, [router]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "register") {
        await api.register(email.trim(), password);
        const data = await api.login(email.trim(), password);
        setAccessToken(data.access_token);
      } else {
        const data = await api.login(email.trim(), password);
        setAccessToken(data.access_token);
      }
      router.push("/dashboard");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败");
    } finally {
      setBusy(false);
    }
  }

  async function handleGithubLogin() {
    setBusy(true);
    setError(null);
    try {
      const data = await api.startGithubOAuth();
      window.location.assign(data.auth_url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "GitHub 登录失败");
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-md">
      <h1 className="mb-2 text-2xl font-bold text-slate-900">
        {mode === "login" ? "登录 FixPilot" : "注册账号"}
      </h1>
      <p className="mb-6 text-sm text-slate-600">
        使用邮箱和密码登录，登录后可管理修复任务。
      </p>

      <div className="mb-4 flex gap-2 text-sm">
        <button
          type="button"
          onClick={() => setMode("login")}
          className={`rounded px-3 py-1 ${mode === "login" ? "bg-blue-600 text-white" : "bg-slate-200"}`}
        >
          登录
        </button>
        <button
          type="button"
          onClick={() => setMode("register")}
          className={`rounded px-3 py-1 ${mode === "register" ? "bg-blue-600 text-white" : "bg-slate-200"}`}
        >
          注册
        </button>
      </div>

      <form
        onSubmit={handleSubmit}
        className="space-y-4 rounded-lg border border-slate-200 bg-white p-6"
      >
        <label className="block text-sm">
          <span className="font-medium text-slate-700">邮箱</span>
          <input
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
          />
        </label>
        <label className="block text-sm">
          <span className="font-medium text-slate-700">密码</span>
          <input
            type="password"
            required
            minLength={8}
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
          />
          {mode === "register" && (
            <span className="mt-1 block text-xs text-slate-500">至少 8 位</span>
          )}
        </label>

        {error && (
          <p className="rounded bg-red-50 p-2 text-sm text-red-800">{error}</p>
        )}

        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-md bg-blue-600 py-2 text-white disabled:opacity-50"
        >
          {busy ? "请稍候…" : mode === "login" ? "登录" : "注册并登录"}
        </button>

        <button
          type="button"
          disabled={busy}
          onClick={handleGithubLogin}
          className="w-full rounded-md border border-slate-300 bg-white py-2 text-slate-900 disabled:opacity-50"
        >
          使用 GitHub 登录
        </button>
      </form>

      <p className="mt-4 text-center text-sm text-slate-500">
        <Link href="/dashboard" className="text-blue-600 hover:underline">
          暂不登录，浏览任务列表
        </Link>
      </p>
    </div>
  );
}

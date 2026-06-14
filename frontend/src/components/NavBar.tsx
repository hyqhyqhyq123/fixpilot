"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { clearAccessToken, getAccessToken } from "@/lib/auth";
import type { AuthUser } from "@/lib/types";

export function NavBar() {
  const router = useRouter();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  const loadUser = useCallback(async () => {
    if (!getAccessToken()) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      const me = await api.getMe();
      setUser(me);
    } catch {
      clearAccessToken();
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadUser();
  }, [loadUser]);

  async function handleLogout() {
    try {
      if (getAccessToken()) {
        await api.logout();
      }
    } catch {
      /* 即使后端失败也清除本地 token */
    }
    clearAccessToken();
    setUser(null);
    router.push("/login");
  }

  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-6xl flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        <Link href="/dashboard" className="text-lg font-bold text-slate-900">
          FixPilot
        </Link>
        <nav className="flex w-full flex-wrap items-center gap-3 text-sm sm:w-auto sm:gap-4">
          <Link href="/dashboard" className="text-slate-600 hover:text-slate-900">
            任务列表
          </Link>
          <Link
            href="/tasks/new"
            className="rounded-md bg-blue-600 px-3 py-1.5 text-white hover:bg-blue-700"
          >
            新建任务
          </Link>
          <Link href="/settings" className="text-slate-600 hover:text-slate-900">
            设置
          </Link>
          {!loading && user && (
            <span className="text-slate-600">{user.email}</span>
          )}
          {!loading && user ? (
            <button
              type="button"
              onClick={handleLogout}
              className="text-slate-600 hover:text-slate-900"
            >
              退出
            </button>
          ) : (
            !loading && (
              <Link href="/login" className="text-blue-600 hover:underline">
                登录
              </Link>
            )
          )}
        </nav>
      </div>
    </header>
  );
}

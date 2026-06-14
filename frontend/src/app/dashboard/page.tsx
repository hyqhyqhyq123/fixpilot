"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { TaskStatusBadge } from "@/components/TaskStatusBadge";
import { formatLocalDateTime } from "@/lib/date";
import type { FixTask } from "@/lib/types";

export default function DashboardPage() {
  const [tasks, setTasks] = useState<FixTask[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.listTasks(1, 50);
      setTasks(data.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div>
      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <h1 className="text-2xl font-bold text-slate-900">任务列表</h1>
        <button
          type="button"
          onClick={load}
          className="text-sm text-blue-600 hover:underline"
        >
          刷新
        </button>
      </div>

      {error && (
        <div className="mb-4 rounded-lg bg-red-50 p-4 text-sm text-red-800">
          {error}
          <p className="mt-2 text-xs text-red-600">
            请确认后端已启动：uvicorn app.main:app --port 8000
          </p>
        </div>
      )}

      {loading ? (
        <p className="text-slate-500">加载中…</p>
      ) : tasks.length === 0 ? (
        <p className="text-slate-500">
          暂无任务，{" "}
          <Link href="/tasks/new" className="text-blue-600 hover:underline">
            创建第一个任务
          </Link>
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="min-w-[760px] text-left text-sm">
            <thead className="bg-slate-50 text-slate-600">
              <tr>
                <th className="px-4 py-3 font-medium">ID</th>
                <th className="px-4 py-3 font-medium">仓库</th>
                <th className="px-4 py-3 font-medium">状态</th>
                <th className="px-4 py-3 font-medium">当前 Agent</th>
                <th className="px-4 py-3 font-medium">创建时间</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((task) => (
                <tr key={task.id} className="border-t border-slate-100 hover:bg-slate-50">
                  <td className="px-4 py-3">
                    <Link
                      href={`/tasks/${task.id}`}
                      className="font-medium text-blue-600 hover:underline"
                    >
                      #{task.id}
                    </Link>
                  </td>
                  <td className="max-w-xs truncate px-4 py-3" title={task.repo_url}>
                    {task.repo_url.replace("https://github.com/", "")}
                  </td>
                  <td className="px-4 py-3">
                    <TaskStatusBadge status={task.status} />
                  </td>
                  <td className="px-4 py-3 text-slate-600">
                    {task.current_agent ?? "—"}
                  </td>
                  <td className="px-4 py-3 text-slate-500">
                    {formatLocalDateTime(task.created_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

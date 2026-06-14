import type { TaskStatus } from "@/lib/types";

const STATUS_LABEL: Record<TaskStatus, string> = {
  pending: "待启动",
  running: "运行中",
  waiting_approval: "待审批",
  success: "成功",
  failed: "失败",
  cancelled: "已取消",
};

const STATUS_CLASS: Record<TaskStatus, string> = {
  pending: "bg-slate-100 text-slate-700",
  running: "bg-blue-100 text-blue-800",
  waiting_approval: "bg-amber-100 text-amber-900",
  success: "bg-emerald-100 text-emerald-800",
  failed: "bg-red-100 text-red-800",
  cancelled: "bg-gray-100 text-gray-600",
};

export function TaskStatusBadge({ status }: { status: TaskStatus }) {
  return (
    <span
      className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_CLASS[status] ?? STATUS_CLASS.pending}`}
    >
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

const HAS_TIMEZONE = /(?:Z|[+-]\d{2}:?\d{2})$/;

/**
 * SQLite-backed API responses can omit timezone information, for example:
 * "2026-06-11T08:53:16". These values are UTC, but browsers parse
 * timezone-less ISO strings as local time. We add "Z" for that case, then
 * render in the user's browser timezone.
 */
export function parseApiDate(value: string): Date {
  if (!value) return new Date(Number.NaN);
  return new Date(HAS_TIMEZONE.test(value) ? value : `${value}Z`);
}

export function formatLocalDateTime(value: string): string {
  const date = parseApiDate(value);
  if (Number.isNaN(date.getTime())) return value;

  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

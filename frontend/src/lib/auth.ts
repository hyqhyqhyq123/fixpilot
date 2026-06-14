/**
 * 浏览器端 JWT 存储（localStorage）
 * JWT = 登录成功后后端发的「通行证」，后续请求放在 Authorization 头里
 */

const TOKEN_KEY = "fixpilot_access_token";

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setAccessToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearAccessToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export function isLoggedIn(): boolean {
  return Boolean(getAccessToken());
}

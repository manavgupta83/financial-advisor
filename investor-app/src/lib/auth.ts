/**
 * lib/auth.ts — Token storage, JWT decode, logout
 */
import { jwtDecode } from "jwt-decode";

export interface TokenPayload {
  sub: string;
  role: "investor" | "advisor" | "admin";
  client_id: number | null;
  user_id: number;
  exp: number;
}

export function saveTokens(accessToken: string, refreshToken: string) {
  localStorage.setItem("access_token", accessToken);
  localStorage.setItem("refresh_token", refreshToken);
}
export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("access_token");
}
export function clearTokens() {
  localStorage.removeItem("access_token");
  localStorage.removeItem("refresh_token");
}
export function getUser(): TokenPayload | null {
  const token = getAccessToken();
  if (!token) return null;
  try {
    const payload = jwtDecode<TokenPayload>(token);
    if (payload.exp * 1000 < Date.now()) { clearTokens(); return null; }
    return payload;
  } catch { return null; }
}
export function isLoggedIn(): boolean { return getUser() !== null; }
export function logout() { clearTokens(); window.location.href = "/login"; }

/* ─── Local API-key session ───────────────────────────────────────
 * Single-user, local-first dashboard. The operator enters the backend
 * API_SECRET_KEY once per browser tab; it lives in sessionStorage and is
 * sent as X-API-Key. It is never bundled into the client.
 * ──────────────────────────────────────────────────────────────── */

const API_KEY_STORAGE = "ares_api_key";

export function getApiKey(): string | null {
  if (typeof window === "undefined") return null;
  return window.sessionStorage.getItem(API_KEY_STORAGE);
}

export function setApiKey(key: string): void {
  if (typeof window === "undefined") return;
  window.sessionStorage.setItem(API_KEY_STORAGE, key);
}

export function clearApiKey(): void {
  if (typeof window === "undefined") return;
  window.sessionStorage.removeItem(API_KEY_STORAGE);
}

// Local dev: empty string -> Vite proxy handles /api -> :8000.
// Prod: set VITE_API_URL in Vercel env to the Render backend URL (no trailing slash).
const API_BASE = import.meta.env.VITE_API_URL ?? "";

/** Machine-readable code the vault guard sends with its 403. Mirrors app/authz.py. */
export const REVERIFICATION_REQUIRED = "reverification_required";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** True when the backend is asking for a fresh passkey assertion, not reporting a real failure. */
export function needsReverification(err: unknown): boolean {
  return err instanceof ApiError && err.status === 403 && err.code === REVERIFICATION_REQUIRED;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(API_BASE + path, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!res.ok) {
    // FastAPI's `detail` is a plain string for most errors, but the vault guard sends
    // an object so the client can act on the reason rather than parse prose.
    let message = res.statusText;
    let code: string | undefined;
    try {
      const { detail } = await res.json();
      if (typeof detail === "string") {
        message = detail;
      } else if (detail && typeof detail === "object") {
        code = detail.code;
        message = detail.message ?? message;
      }
    } catch {
      /* ignore */
    }
    throw new ApiError(message, res.status, code);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export type VaultEntry = {
  id: string;
  label: string;
  username: string;
  password: string;
  created_at: string;
};

export const api = {
  registerBegin: (username: string) =>
    request<{ options: any }>("/api/webauthn/register/begin", {
      method: "POST",
      body: JSON.stringify({ username }),
    }),
  registerComplete: (username: string, attestation: unknown) =>
    request<{ username: string }>("/api/webauthn/register/complete", {
      method: "POST",
      body: JSON.stringify({ username, attestation }),
    }),
  loginBegin: (username: string) =>
    request<{ options: any }>("/api/webauthn/login/begin", {
      method: "POST",
      body: JSON.stringify({ username }),
    }),
  loginComplete: (username: string, assertion: unknown) =>
    request<{ username: string }>("/api/webauthn/login/complete", {
      method: "POST",
      body: JSON.stringify({ username, assertion }),
    }),
  reverifyBegin: () =>
    request<{ options: any }>("/api/webauthn/reverify/begin", { method: "POST" }),
  reverifyComplete: (assertion: unknown) =>
    request<{ username: string }>("/api/webauthn/reverify/complete", {
      method: "POST",
      body: JSON.stringify({ assertion }),
    }),
  whoami: () => request<{ username: string }>("/api/vault/whoami"),
  signout: () => request<{ ok: boolean }>("/api/vault/signout", { method: "POST" }),
  listVault: () => request<VaultEntry[]>("/api/vault"),
  createVault: (entry: { label: string; username: string; password: string }) =>
    request<VaultEntry>("/api/vault", { method: "POST", body: JSON.stringify(entry) }),
  deleteVault: (id: string) => request<void>(`/api/vault/${id}`, { method: "DELETE" }),
};

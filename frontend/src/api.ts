async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
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
  whoami: () => request<{ username: string }>("/api/vault/whoami"),
  signout: () => request<{ ok: boolean }>("/api/vault/signout", { method: "POST" }),
  listVault: () => request<VaultEntry[]>("/api/vault"),
  createVault: (entry: { label: string; username: string; password: string }) =>
    request<VaultEntry>("/api/vault", { method: "POST", body: JSON.stringify(entry) }),
  deleteVault: (id: string) => request<void>(`/api/vault/${id}`, { method: "DELETE" }),
};

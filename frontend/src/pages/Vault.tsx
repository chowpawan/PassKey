import { useEffect, useRef, useState } from "react";
import { api, needsReverification, type VaultEntry } from "../api";
import { reverifyPasskey } from "../webauthn";
import VaultEntryForm from "../components/VaultEntryForm";

type Props = { username: string; onSignout: () => void };

export default function Vault({ username, onSignout }: Props) {
  const [entries, setEntries] = useState<VaultEntry[]>([]);
  const [revealed, setRevealed] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [locked, setLocked] = useState(false);
  const [unlocking, setUnlocking] = useState(false);

  // What to re-run once the user unlocks. Only for actions with nothing to preserve
  // in the UI — a half-typed new entry is left to the form instead.
  const pending = useRef<(() => Promise<void>) | null>(null);

  /**
   * Run a vault call, turning the guard's 403 into the lock screen rather than an
   * error message. Anything else is a real failure and propagates. Returns false if
   * the call was blocked, since callers can't read the freshly-set `locked` state.
   */
  async function guarded(fn: () => Promise<void>, retryAfterUnlock = true): Promise<boolean> {
    try {
      await fn();
      return true;
    } catch (err) {
      if (needsReverification(err)) {
        pending.current = retryAfterUnlock ? fn : null;
        setLocked(true);
        // Locked means locked: drop the decrypted entries this page was holding.
        setEntries([]);
        setRevealed({});
        return false;
      }
      throw err;
    }
  }

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      await guarded(async () => {
        setEntries(await api.listVault());
        setLocked(false);
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function onUnlock() {
    setUnlocking(true);
    setError(null);
    try {
      await reverifyPasskey();
      setLocked(false);

      const retry = pending.current;
      pending.current = null;
      if (retry) await retry();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setUnlocking(false);
    }
  }

  async function onCreate(entry: { label: string; username: string; password: string }) {
    // Not retried after unlocking: rethrowing keeps the typed entry in the form, so
    // the user unlocks and presses Save again rather than watching it save itself.
    const saved = await guarded(async () => {
      const created = await api.createVault(entry);
      setEntries((prev) => [created, ...prev]);
    }, false);
    if (!saved) throw new Error("Vault locked — unlock with your passkey, then save.");
  }

  async function onDelete(id: string) {
    try {
      await guarded(async () => {
        await api.deleteVault(id);
        setEntries((prev) => prev.filter((e) => e.id !== id));
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="page">
      <div className="nav">
        <div>
          <h1 style={{ margin: 0 }}>Vault</h1>
          <div className="muted">Signed in as <strong>{username}</strong></div>
        </div>
        <button className="secondary" onClick={onSignout}>Sign out</button>
      </div>

      {locked && (
        <div className="notice">
          <div>
            <strong>Vault locked</strong>
            <div className="muted">
              You're still signed in, but it's been a while since your last passkey check.
            </div>
          </div>
          <button onClick={onUnlock} disabled={unlocking}>
            {unlocking ? "Waiting…" : "Unlock with passkey"}
          </button>
        </div>
      )}

      {error && <div className="error">{error}</div>}
      {loading && <p className="muted">Loading…</p>}

      {!loading && !locked && entries.length === 0 && (
        <p className="muted">No entries yet — add one below.</p>
      )}

      {entries.map((entry) => (
        <div className="entry" key={entry.id}>
          <div>
            <div><strong>{entry.label}</strong></div>
            <div className="entry-meta">{entry.username}</div>
            <div className="entry-meta">
              {revealed[entry.id] ? (
                <code>{entry.password}</code>
              ) : (
                <code>••••••••</code>
              )}{" "}
              <button
                className="link"
                onClick={() =>
                  setRevealed((r) => ({ ...r, [entry.id]: !r[entry.id] }))
                }
              >
                {revealed[entry.id] ? "hide" : "reveal"}
              </button>
            </div>
          </div>
          <button className="secondary" onClick={() => onDelete(entry.id)}>
            Delete
          </button>
        </div>
      ))}

      <VaultEntryForm onCreate={onCreate} />
    </div>
  );
}

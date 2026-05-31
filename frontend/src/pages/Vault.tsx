import { useEffect, useState } from "react";
import { api, type VaultEntry } from "../api";
import VaultEntryForm from "../components/VaultEntryForm";

type Props = { username: string; onSignout: () => void };

export default function Vault({ username, onSignout }: Props) {
  const [entries, setEntries] = useState<VaultEntry[]>([]);
  const [revealed, setRevealed] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    setLoading(true);
    try {
      setEntries(await api.listVault());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function onCreate(entry: { label: string; username: string; password: string }) {
    const created = await api.createVault(entry);
    setEntries((prev) => [created, ...prev]);
  }

  async function onDelete(id: string) {
    await api.deleteVault(id);
    setEntries((prev) => prev.filter((e) => e.id !== id));
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

      {error && <div className="error">{error}</div>}
      {loading && <p className="muted">Loading…</p>}

      {!loading && entries.length === 0 && (
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

import { useState } from "react";

type Props = {
  onCreate: (entry: { label: string; username: string; password: string }) => Promise<void>;
};

export default function VaultEntryForm({ onCreate }: Props) {
  const [label, setLabel] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await onCreate({ label: label.trim(), username: username.trim(), password });
      setLabel("");
      setUsername("");
      setPassword("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} style={{ borderTop: "1px solid #eee", paddingTop: "1rem" }}>
      <h2>Add entry</h2>
      <div className="field">
        <label>Label</label>
        <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="github.com" required />
      </div>
      <div className="field">
        <label>Username</label>
        <input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="alice@example.com" />
      </div>
      <div className="field">
        <label>Password</label>
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
      </div>
      {error && <div className="error">{error}</div>}
      <button type="submit" disabled={busy || !label.trim() || !password}>
        {busy ? "Saving…" : "Save"}
      </button>
    </form>
  );
}

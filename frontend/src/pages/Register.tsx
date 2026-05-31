import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { registerPasskey } from "../webauthn";

type Props = { onAuthed: (username: string) => void };

export default function Register({ onAuthed }: Props) {
  const [username, setUsername] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await registerPasskey(username.trim());
      onAuthed(username.trim());
      navigate("/vault");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <h1>Create a PassKey account</h1>
      <p className="muted">
        Pick a username, then your device will prompt you to create a passkey
        (Touch ID, Face ID, Windows Hello, security key).
      </p>
      <form onSubmit={onSubmit}>
        <div className="field">
          <label htmlFor="username">Username</label>
          <input
            id="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="alice"
            autoFocus
            required
          />
        </div>
        {error && <div className="error">{error}</div>}
        <button type="submit" disabled={busy || !username.trim()}>
          {busy ? "Waiting for passkey…" : "Create passkey"}
        </button>
      </form>
      <p className="muted" style={{ marginTop: "1.5rem" }}>
        Already have an account? <Link className="link" to="/login">Sign in</Link>
      </p>
    </div>
  );
}

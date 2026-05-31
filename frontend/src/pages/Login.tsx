import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { loginWithPasskey } from "../webauthn";

type Props = { onAuthed: (username: string) => void };

export default function Login({ onAuthed }: Props) {
  const [username, setUsername] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await loginWithPasskey(username.trim());
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
      <h1>Sign in to PassKey</h1>
      <p className="muted">Authenticate with the passkey you registered earlier.</p>
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
          {busy ? "Waiting for passkey…" : "Sign in with passkey"}
        </button>
      </form>
      <p className="muted" style={{ marginTop: "1.5rem" }}>
        New here? <Link className="link" to="/register">Create an account</Link>
      </p>
    </div>
  );
}

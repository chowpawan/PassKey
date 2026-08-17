import { useEffect, useState } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { api, type Role } from "./api";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Vault from "./pages/Vault";

export default function App() {
  const [username, setUsername] = useState<string | null>(null);
  // Null until whoami answers. Routing stays keyed on username so signing in doesn't
  // race the role fetch and bounce the user back to /login.
  const [role, setRole] = useState<Role | null>(null);
  const [loaded, setLoaded] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    api
      .whoami()
      .then((me) => {
        setUsername(me.username);
        setRole(me.role);
      })
      .catch(() => setUsername(null))
      .finally(() => setLoaded(true));
  }, []);

  function onAuthed(name: string) {
    setUsername(name);
    // A ceremony doesn't report the role, so ask. Until it lands the UI is optimistic;
    // the server-side guard is what actually enforces.
    api.whoami().then((me) => setRole(me.role)).catch(() => setRole(null));
  }

  async function onSignout() {
    await api.signout();
    setUsername(null);
    setRole(null);
    navigate("/login");
  }

  if (!loaded) return null;

  return (
    <Routes>
      <Route
        path="/"
        element={<Navigate to={username ? "/vault" : "/login"} replace />}
      />
      <Route
        path="/register"
        element={<Register onAuthed={onAuthed} />}
      />
      <Route
        path="/login"
        element={<Login onAuthed={onAuthed} />}
      />
      <Route
        path="/vault"
        element={
          username ? (
            <Vault username={username} role={role} onSignout={onSignout} />
          ) : (
            <Navigate to="/login" replace />
          )
        }
      />
    </Routes>
  );
}

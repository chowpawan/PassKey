import { useEffect, useState } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { api } from "./api";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Vault from "./pages/Vault";

export default function App() {
  const [username, setUsername] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    api
      .whoami()
      .then((res) => setUsername(res.username))
      .catch(() => setUsername(null))
      .finally(() => setLoaded(true));
  }, []);

  async function onSignout() {
    await api.signout();
    setUsername(null);
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
        element={<Register onAuthed={(u) => setUsername(u)} />}
      />
      <Route
        path="/login"
        element={<Login onAuthed={(u) => setUsername(u)} />}
      />
      <Route
        path="/vault"
        element={
          username ? (
            <Vault username={username} onSignout={onSignout} />
          ) : (
            <Navigate to="/login" replace />
          )
        }
      />
    </Routes>
  );
}

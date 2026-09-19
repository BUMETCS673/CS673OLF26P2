/**
 * The signed-in header — WS3 (Duc).
 *
 * Renders nothing at all when nobody is signed in, so the login and signup pages stay
 * clean without App.jsx having to know which route is which.
 */

import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";

export default function Header() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [leaving, setLeaving] = useState(false);

  if (!user) return null;

  async function handleLogout() {
    setLeaving(true);
    try {
      await logout();
      navigate("/login", { replace: true });
    } finally {
      setLeaving(false);
    }
  }

  return (
    <header className="app-header">
      <Link className="app-brand" to="/decks">
        Cadence
      </Link>
      <div className="app-header-user">
        {/* display_name is optional in the contract, so fall back to the email. */}
        <span className="app-header-name">{user.display_name || user.email}</span>
        <button type="button" onClick={handleLogout} disabled={leaving}>
          {leaving ? "Signing out…" : "Sign out"}
        </button>
      </div>
    </header>
  );
}

/**
 * Route guards — WS3 (Duc).
 *
 * `ProtectedRoute` keeps signed-out visitors off the deck pages. `GuestOnlyRoute` is
 * the mirror of it: someone already signed in has no reason to see the login form.
 *
 * Both wait for the page-load `/me` call to answer before deciding. Redirecting while
 * that's still in flight is what makes a refresh throw you out.
 */

import { Navigate, useLocation } from "react-router-dom";

import { useAuth } from "./AuthContext";

function Checking() {
  return <p className="page-status">Loading…</p>;
}

export default function ProtectedRoute({ children }) {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) return <Checking />;

  if (!user) {
    // `replace` so the back button doesn't walk into the page we just bounced them off,
    // and `state.from` so login can send them where they were actually going.
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return children;
}

export function GuestOnlyRoute({ children }) {
  const { user, loading } = useAuth();

  if (loading) return <Checking />;
  if (user) return <Navigate to="/decks" replace />;

  return children;
}

/**
 * Who's signed in, for the whole app — WS3 (Duc).
 *
 * Asks `GET /api/auth/me` once when the page loads. That single call is what makes a
 * refresh keep you signed in: the session cookie is already in the browser, so the
 * answer comes back with the user and nothing has to be stored on our side.
 *
 * Nothing about the user is kept in localStorage. The cookie is the session, it's
 * HttpOnly, and a copy in storage would only be a second source of truth to go stale.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import * as authApi from "../api/auth";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  // True until /me answers. Routes wait on this -- deciding before the answer arrives
  // would bounce a signed-in user to /login on every refresh.
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    authApi
      .me()
      .then((signedIn) => {
        if (!cancelled) setUser(signedIn);
      })
      .catch((err) => {
        // A 401 here is the ordinary "nobody is signed in" answer, not a failure.
        if (err.code !== "unauthorized") {
          console.error("Couldn't check the session:", err);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  // Both of these return the User, and both throw ApiError on failure so the form that
  // called them can show the message next to the right field.
  const login = useCallback(async (credentials) => {
    const signedIn = await authApi.login(credentials);
    setUser(signedIn);
    return signedIn;
  }, []);

  const register = useCallback(async (details) => {
    // Register signs you in as well, so there's no second call here.
    const signedIn = await authApi.register(details);
    setUser(signedIn);
    return signedIn;
  }, []);

  const logout = useCallback(async () => {
    try {
      await authApi.logout();
    } finally {
      // Clear locally whatever the server said. If the request failed we still want the
      // app to behave as signed out; the protected routes will re-check on the next call.
      setUser(null);
    }
  }, []);

  const value = useMemo(
    () => ({ user, loading, login, register, logout }),
    [user, loading, login, register, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === null) {
    throw new Error("useAuth() must be used inside <AuthProvider>.");
  }
  return context;
}

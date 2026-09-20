/**
 * All five routes — WS3 (Duc) owns this file.
 *
 * Shared file: WS4's pages are already wired up here against placeholders, so Nurzat
 * fills those in without anyone editing this file a second time. See "Shared files"
 * in ITERATION_1_PLAN.md.
 */

import { Navigate, Route, Routes } from "react-router-dom";

import Header from "./components/Header";
import ProtectedRoute, { GuestOnlyRoute } from "./auth/ProtectedRoute";
import DeckDetailPage from "./pages/DeckDetailPage";
import DeckListPage from "./pages/DeckListPage";
import LoginPage from "./pages/LoginPage";
import SignupPage from "./pages/SignupPage";

export default function App() {
  return (
    <>
      <Header />
      <Routes>
        <Route path="/" element={<Navigate to="/decks" replace />} />

        <Route
          path="/login"
          element={
            <GuestOnlyRoute>
              <LoginPage />
            </GuestOnlyRoute>
          }
        />
        <Route
          path="/signup"
          element={
            <GuestOnlyRoute>
              <SignupPage />
            </GuestOnlyRoute>
          }
        />

        <Route
          path="/decks"
          element={
            <ProtectedRoute>
              <DeckListPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/decks/:id"
          element={
            <ProtectedRoute>
              <DeckDetailPage />
            </ProtectedRoute>
          }
        />

        {/* Anything else goes home, which then decides login or decks. */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  );
}

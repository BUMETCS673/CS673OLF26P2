/**
 * Every route — WS3 (Duc) owns this file.
 *
 * Shared file: WS4's pages are already wired up here against placeholders, so Nurzat
 * fills those in without anyone editing this file a second time. See "Shared files"
 * in code/plans/ITERATION_1_PLAN.md. Iteration 2's study page was added the same way,
 * by Step 0b in code/plans/FINALIZE_ITERATION_2_PLAN.md, and Iteration 3's generate
 * page by Step 0b in code/plans/ITERATION_3_PLAN.md.
 */

/*
 * Step 0b: the StudyPage import and the /decks/:id/study route.
 * AI Utilization: ~100% of that code
 * AI Tools Used: Claude Code (Claude Opus 5.5)
 * AI-Assisted Activities:
 *   Routing
 * Human role: plan approval, code review, and hands-on testing by Miles Cameron.
 */

/*
 * Iteration 3, Step 0b: the GeneratePage import and the /decks/:id/generate route.
 * AI Utilization: ~100% of that code
 * AI Tools Used: Claude Code (Claude Opus 5.5)
 * AI-Assisted Activities:
 *   Routing
 * Human role: plan approval, code review, and hands-on testing by Miles Cameron.
 */

import { Navigate, Route, Routes } from "react-router-dom";

import Header from "./components/Header";
import ProtectedRoute, { GuestOnlyRoute } from "./auth/ProtectedRoute";
import DeckDetailPage from "./pages/DeckDetailPage";
import DeckListPage from "./pages/DeckListPage";
import GeneratePage from "./pages/GeneratePage";
import LoginPage from "./pages/LoginPage";
import SignupPage from "./pages/SignupPage";
import StudyPage from "./pages/StudyPage";

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
        <Route
          path="/decks/:id/study"
          element={
            <ProtectedRoute>
              <StudyPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/decks/:id/generate"
          element={
            <ProtectedRoute>
              <GeneratePage />
            </ProtectedRoute>
          }
        />

        {/* Anything else goes home, which then decides login or decks. */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  );
}

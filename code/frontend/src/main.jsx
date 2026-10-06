/*
 * Step 0c: the stylesheets' load order, and the comment that explains it.
 * AI Utilization: ~100% of that change
 * AI Tools Used: Claude Code (Claude Opus 5.5)
 * AI-Assisted Activities:
 *   Design system setup
 * Human role: plan approval, code review, and hands-on testing by Miles Cameron.
 */

import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

// The design system loads first, then the page stylesheets: ws4.css here, and the ones
// pages import themselves (study.css), which arrive through App below. A page rule
// then beats a shared rule of the same specificity, instead of silently losing to it.
import "./styles.css";
import "./ws4.css";
import App from "./App";
import { AuthProvider } from "./auth/AuthContext";

// AuthProvider sits inside the router so route guards and the header can both read the
// current user, and so AuthProvider's own children may use hooks like useNavigate.
ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <App />
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>,
);

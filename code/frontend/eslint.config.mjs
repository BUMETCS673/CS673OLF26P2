// ESLint 9 flat config. Named .mjs because package.json has no "type": "module".
//
// The CI job installs eslint and these plugins with `npm install --no-save`, so they are
// deliberately absent from package.json: adding them would require regenerating
// package-lock.json, and `npm ci` (used here and in the Dockerfile) fails when the two
// disagree. Fold them into devDependencies the next time someone runs npm locally.

import js from "@eslint/js";
import globals from "globals";
import react from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";

export default [
  { ignores: ["dist/**", "node_modules/**"] },

  js.configs.recommended,

  {
    files: ["src/**/*.{js,jsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: globals.browser,
      parserOptions: {
        ecmaFeatures: { jsx: true },
      },
    },
    plugins: {
      react,
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    settings: {
      react: { version: "detect" },
    },
    rules: {
      ...reactHooks.configs.recommended.rules,

      // Without this, plain eslint has no idea that <DeckListPage /> is a *use* of the
      // imported DeckListPage, so no-unused-vars flags every component in the project.
      // jsx-uses-react does the same for the React identifier itself.
      "react/jsx-uses-vars": "error",
      "react/jsx-uses-react": "error",

      // Catches the bug class this project is most exposed to: a fetch in an effect
      // whose dependency list is missing the id it reads, so the deck detail page keeps
      // showing the previous deck's cards.
      "react-hooks/exhaustive-deps": "error",

      // Fast Refresh silently stops working for a module that exports a component plus
      // something else. AuthContext.jsx is exactly that shape, so allow constants.
      "react-refresh/only-export-components": [
        "warn",
        { allowConstantExport: true },
      ],

      // An unused variable is usually a half-finished edit. Leading underscore opts out,
      // for the "I need the second callback argument only" case.
      "no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],

      // console.error is how the API client surfaces failures; console.log is debris.
      "no-console": ["error", { allow: ["warn", "error"] }],
    },
  },

  {
    // Node's built-in test runner, not a browser: different globals, and test files are
    // allowed to print.
    files: ["tests/**/*.{js,mjs}", "*.config.{js,mjs}"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: { ...globals.node },
    },
    rules: {
      "no-console": "off",
    },
  },
];

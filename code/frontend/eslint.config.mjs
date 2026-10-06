// ESLint 9 flat config. Named .mjs because package.json has no "type": "module".
//
// eslint and these plugins are devDependencies, so `npx eslint .` works on your machine
// after `npm ci`, the same as in CI.

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
    // Tests run under Vitest in Node (component tests in a simulated browser), and config
    // files run under Node: different globals, and both are allowed to print. Component
    // tests are .jsx, so JSX parsing and the two rules that let eslint see JSX as a use of
    // an import are needed here too -- without this block eslint silently skips them.
    files: ["tests/**/*.{js,mjs,jsx}", "*.config.{js,mjs}"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: { ...globals.node },
      parserOptions: {
        ecmaFeatures: { jsx: true },
      },
    },
    plugins: {
      react,
    },
    settings: {
      react: { version: "detect" },
    },
    rules: {
      "react/jsx-uses-vars": "error",
      "react/jsx-uses-react": "error",
      "no-console": "off",
    },
  },
];

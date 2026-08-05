import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

/**
 * Flat config for the Vite + React + TypeScript SPA.
 *
 * The rules that earn their place here are the react-hooks ones. This app's
 * state lives in Zustand stores read through selectors, and the two bugs that
 * have actually reached the browser were both of that shape: a selector
 * returning a fresh array literal on every call, and an effect whose
 * dependencies did not match what it read. Neither is a type error, so `tsc`
 * cannot catch them.
 */
export default tseslint.config(
  {
    ignores: [
      "backend/**",
      "dist/**",
      "node_modules/**",
      "**/*.config.js",
      "**/*.config.cjs",
    ],
  },

  js.configs.recommended,
  ...tseslint.configs.recommended,

  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs["recommended-latest"].rules,

      // Vite's fast refresh only works when a module exports components and
      // nothing else. A warning rather than an error: a few files legitimately
      // export a constant beside their component.
      "react-refresh/only-export-components": [
        "warn",
        { allowConstantExport: true },
      ],

      // An unused parameter is often deliberate — matching a callback shape, or
      // discarding a caught error whose type is all the information needed.
      // Underscore is the escape hatch, and it has to be written on purpose.
      "@typescript-eslint/no-unused-vars": [
        "error",
        {
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
          caughtErrors: "none",
        },
      ],
    },
  },
);

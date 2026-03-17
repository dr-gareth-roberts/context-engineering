# Server, Config & CI Deep Audit

**Date:** 2026-03-17
**Scope:** `packages/ce-web-server/`, root config, `.github/workflows/`, `schemas/`, related config files
**Auditor:** Automated deep audit

---

## Summary

The monorepo is well-structured overall, but the Express server has significant security gaps, the CI pipeline does not run unit tests, several root dependencies are unused, the JSON schemas have non-standard `$ref` usage and drift from the actual TS/Python types, and there are multiple stale references to a previous `client/`/`server/` directory layout.

**Issue counts:** 5 CRITICAL, 8 HIGH, 11 MEDIUM, 8 LOW, 6 NOTES

---

## Critical Issues

### C1. CI does not run any unit tests (ci.yml line 39)

**File:** `.github/workflows/ci.yml` line 39
**Severity:** CRITICAL

The CI workflow runs `pnpm test`, which is defined in root `package.json` line 28 as:

```json
"test": "pnpm run check && pnpm run build:app"
```

This only runs type-checking and the Vite+esbuild build. **No Vitest tests are ever executed in CI.** The 389+ TypeScript tests only run in the publish workflow (`pnpm test:all`), meaning broken tests can be merged to `main` without detection.

**Fix:** Change CI step to `pnpm test:all`, or at minimum add `pnpm test:packages` as a separate step.

---

### C2. No security headers on static file serving (server/index.ts)

**File:** `packages/ce-web-server/index.ts` lines 91-96
**Severity:** CRITICAL

The Express server serves static files and the SPA fallback with zero security headers:

- No `X-Content-Type-Options: nosniff`
- No `X-Frame-Options: DENY`
- No `Content-Security-Policy`
- No `Strict-Transport-Security`
- No `X-XSS-Protection`
- No `Referrer-Policy`

This is a deployment-blocking issue for any production use. The `helmet` middleware would cover all of these in one line.

---

### C3. Rate limiter memory leak (server/index.ts lines 30-33)

**File:** `packages/ce-web-server/index.ts` lines 30-69
**Severity:** CRITICAL

```ts
const rateLimitState = new Map<string, { count: number; resetAtMs: number }>();
```

This `Map` grows unboundedly. Old entries are only replaced when the same IP returns after its window expires (line 55-56), but IPs that make a single request and never return are **never cleaned up**. Under any traffic volume, this is a memory leak that will eventually crash the process.

**Fix:** Add a periodic cleanup interval (e.g., every 60s, delete entries where `resetAtMs <= Date.now()`), or use a proper rate-limiting library like `express-rate-limit`.

---

### C4. CORS `Access-Control-Allow-Credentials` missing, `Allow-Origin: "*"` in dev (server/index.ts lines 23-46)

**File:** `packages/ce-web-server/index.ts` lines 23-46
**Severity:** CRITICAL

In development, `corsOrigin` defaults to `"*"`. If cookies or auth headers are used (the client has `getLoginUrl()` with OAuth flow in `packages/ce-web-client/src/const.ts` and `COOKIE_NAME` in `shared/const.ts`), wildcard CORS with credentials is rejected by browsers. The server also never sets `Access-Control-Allow-Credentials: true`.

In production, `corsOrigin` defaults to `""` (empty string), which means the `if (corsOrigin)` check on line 36 is falsy, so **no CORS headers are set at all** in production. This will break any cross-origin API calls.

---

### C5. No `trust proxy` configuration (server/index.ts line 52)

**File:** `packages/ce-web-server/index.ts` line 52
**Severity:** CRITICAL

```ts
const ip = req.ip || req.socket.remoteAddress || "unknown";
```

Behind a reverse proxy (which any production deployment will use), `req.ip` returns the proxy's IP, not the client's. Without `app.set('trust proxy', ...)`, the rate limiter applies a single shared limit to **all** clients behind the proxy, and legitimate clients get rate-limited while actual abusers are not individually tracked.

---

## High Priority

### H1. `ce-web-server` and `ce-web-client` are not proper workspace packages

**Files:** `packages/ce-web-server/` (only `index.ts`), `packages/ce-web-client/` (no `package.json`)
**Severity:** HIGH

Neither `ce-web-server` nor `ce-web-client` has a `package.json`. They live under `packages/` but are not part of the workspace (the workspace pattern `packages/*` would match them only if they had `package.json`). Instead, all their dependencies are hoisted to the root `package.json`, mixing server runtime deps (`express`, `http-proxy-middleware`) and client UI deps (`react`, `radix-ui/*`, `recharts`, etc.) with the SDK packages.

This means:

- Server-only deps pollute client builds and vice versa
- Dependency boundaries are invisible
- `pnpm -r` commands skip them entirely (no scripts, no type checking, no tests)
- The server has zero tests

---

### H2. No graceful shutdown handling (server/index.ts)

**File:** `packages/ce-web-server/index.ts` lines 100-106
**Severity:** HIGH

The server does not handle `SIGTERM` or `SIGINT`. In containerized deployments (Docker, Kubernetes), the process receives `SIGTERM` before being killed. Without graceful shutdown, in-flight requests are dropped and the HTTP server doesn't close cleanly.

```ts
// Missing:
// process.on('SIGTERM', () => { server.close(() => process.exit(0)); });
```

---

### H3. `axios` is a root dependency but never imported anywhere

**File:** `package.json` line 82
**Severity:** HIGH

`"axios": "^1.13.5"` is listed in root dependencies but is not imported in any `.ts` or `.tsx` file in the entire codebase. This is dead weight adding ~400KB to `node_modules`.

---

### H4. `@types/google.maps` is a dev dependency for no reason

**File:** `package.json` line 117
**Severity:** HIGH

`"@types/google.maps": "^3.58.1"` is in devDependencies. The only Google Maps reference is `packages/ce-web-client/src/components/Map.tsx`, which is a dead component (see H5). Even if it were used, the type package belongs in the web client package, not the root.

---

### H5. Dead `Map.tsx` component

**File:** `packages/ce-web-client/src/components/Map.tsx`
**Severity:** HIGH

This component is never imported by any other file. It references Google Maps, which is irrelevant to a context engineering toolkit. It appears to be leftover from a template or another project.

---

### H6. Dead OAuth/login code in client

**File:** `packages/ce-web-client/src/const.ts` lines 4-17
**Severity:** HIGH

```ts
export const getLoginUrl = () => {
  const oauthPortalUrl = import.meta.env.VITE_OAUTH_PORTAL_URL;
  const appId = import.meta.env.VITE_APP_ID;
  // ...
```

This function references `VITE_OAUTH_PORTAL_URL` and `VITE_APP_ID` env vars that are never configured (no `.env.example`, no documentation). It constructs an OAuth URL to `/api/oauth/callback`, but the server has no OAuth routes. This is dead code from a template.

---

### H7. `pnpm` listed as devDependency (package.json line 126)

**File:** `package.json` line 126
**Severity:** HIGH

```json
"pnpm": "^10.28.2"
```

`pnpm` should never be a devDependency. It's a package manager installed globally or via corepack. Having it as a dep means it gets installed into `node_modules`, wasting ~50MB+. The `packageManager` field on line 137 (`"pnpm@10.30.3"`) already handles version enforcement via corepack.

---

### H8. Stale ESLint ignores reference non-existent directories

**File:** `eslint.config.js` lines 33-34
**Severity:** HIGH

```js
ignores: [
  // ...
  "client/**",
  "server/**",
  "examples/**",
];
```

`client/` and `server/` directories no longer exist (they were moved to `packages/ce-web-client` and `packages/ce-web-server`). The ESLint config should ignore `packages/ce-web-client/**` and `packages/ce-web-server/**` if intended, but currently the new paths are not ignored (nor linted -- they're not in the `lint` script glob either, though `packages/ce-web-server/**/*.ts` is).

---

## Medium Priority

### M1. `components.json` points to non-existent path

**File:** `components.json` line 7
**Severity:** MEDIUM

```json
"css": "client/src/index.css"
```

Should be `packages/ce-web-client/src/index.css`. This means `npx shadcn` commands will fail or create files in the wrong location.

---

### M2. `vite.config.ts` has dead `@assets` alias (line 19)

**File:** `vite.config.ts` line 19
**Severity:** MEDIUM

```ts
"@assets": path.resolve(import.meta.dirname, "attached_assets"),
```

The `attached_assets/` directory does not exist, and no code imports from `@assets`. Dead configuration.

---

### M3. `downlevelIteration` is unnecessary with ES2022 target

**File:** `tsconfig.json` line 13
**Severity:** MEDIUM

```json
"downlevelIteration": true
```

With `"target": "ES2022"`, iterators and generators are not downleveled, so this flag has no effect. It's misleading.

---

### M4. JSON Schema `$ref` values are non-standard bare names

**Files:** All schemas using `$ref`
**Severity:** MEDIUM

```json
"items": { "$ref": "ContextItem" }
```

Per JSON Schema 2020-12, `$ref` must be a URI-reference. The correct form is either:

- `"$ref": "context-item.schema.json"` (relative file reference)
- `"$ref": "#/$defs/ContextItem"` (local reference)

Bare names like `"ContextItem"` are not valid and will fail with most JSON Schema validators (ajv, jsonschema, etc.) unless a custom resolver is provided.

---

### M5. Schema drift: ContextItem schema missing fields present in TS and Python

**File:** `schemas/context-item.schema.json`
**Severity:** MEDIUM

The TS `ContextItem` type (`packages/ce-core/src/types.ts`) has fields `taskId`, `isOutcome`, `dependsOn` that are not in the schema. The Python `ContextItem` (`python/context_engineering/core.py`) has additional fields: `supersedes`, `embedding`, `parent_id`, `cost`, `latency`, `links`, `task_id`, `is_outcome`, `depends_on`.

The schema says `"additionalProperties": true` which technically allows them, but the purpose of a shared schema is to document the contract. These fields should be explicitly declared (even if optional).

---

### M6. Schema drift: MemoryItem schema missing fields present in Python

**File:** `schemas/memory-item.schema.json`
**Severity:** MEDIUM

Python's `MemoryItem` (`python/context_engineering/memory.py`) has fields `lastAccessedAt`, `isSummary`, `embedding`, `links` that are not in the schema. Like M5, these should be documented.

---

### M7. `tokens` field uses `"type": "number"` but should be `"integer"`

**File:** `schemas/context-item.schema.json` line 13
**Severity:** MEDIUM

Token counts are always whole numbers. In Python, `tokens` is `Optional[int]`. The schema should use `"type": "integer"` for `tokens` (and `compressedTokens` in the trace schema). Compare to `webhook-analytics.schema.json` which correctly uses `"integer"` for token counts.

---

### M8. `tsconfig.json` includes `shared/**/*` but shared/ only has one file

**File:** `tsconfig.json` line 5
**Severity:** MEDIUM

The `shared/` directory contains only `const.ts` (exporting `COOKIE_NAME` and `ONE_YEAR_MS`). These are session/auth constants irrelevant to the SDK. This entire `shared/` pattern appears to be a leftover from a full-stack template and adds unnecessary complexity.

---

### M9. No `.env.example` file

**Severity:** MEDIUM

The server reads `BACKEND_PORT`, `BACKEND_URL`, `CORS_ORIGIN`, `RATE_LIMIT_WINDOW_MS`, `RATE_LIMIT_MAX`, `PORT`, `NODE_ENV`. The client reads `VITE_ANALYTICS_ENDPOINT`, `VITE_ANALYTICS_WEBSITE_ID`, `VITE_OAUTH_PORTAL_URL`, `VITE_APP_ID`. None of these are documented. There is no `.env.example` file.

---

### M10. `pathRewrite` in proxy is a no-op (server/index.ts line 79)

**File:** `packages/ce-web-server/index.ts` lines 79-81
**Severity:** MEDIUM

```ts
pathRewrite: {
  "^/api": "/api", // Keep /api prefix
},
```

Rewriting `/api` to `/api` does nothing. This config option should be removed entirely, or the comment should explain why it's explicitly kept (e.g., as documentation of intent). Currently it's just noise.

---

### M11. Publish workflow does not lint or format-check

**File:** `.github/workflows/publish.yml`
**Severity:** MEDIUM

The publish CI gate runs type checks and tests, but skips linting and formatting. This means a release could go out with lint violations that the regular CI would catch.

---

## Low Priority

### L1. `"jsx": "preserve"` in root tsconfig but Vite handles JSX

**File:** `tsconfig.json` line 17
**Severity:** LOW

With a Vite + `@vitejs/plugin-react` setup, JSX is transformed by Vite/esbuild, not tsc. Using `"jsx": "react-jsx"` would be more accurate and enable better IDE support for automatic JSX import resolution.

---

### L2. Duplicate `build` and `build:app` scripts

**File:** `package.json` lines 21-22
**Severity:** LOW

```json
"build:app": "vite build && esbuild ...",
"build": "vite build && esbuild ...",
```

These are identical. One should delegate to the other, or `build` should be removed/renamed.

---

### L3. `autoprefixer` and `postcss` are likely unused with Tailwind v4

**File:** `package.json` lines 121-127
**Severity:** LOW

Tailwind CSS v4 (`^4.1.14`) uses its own Vite plugin (`@tailwindcss/vite`) and no longer requires PostCSS or Autoprefixer. These deps may be vestigial from a Tailwind v3 setup.

---

### L4. TypeScript version pinned in root but caret-ranged in packages

**File:** Root `package.json` line 132 vs package `package.json` files
**Severity:** LOW

Root: `"typescript": "5.6.3"` (exact pin)
Packages: `"typescript": "^5.6.3"` (caret range)

This can lead to version drift where packages resolve a newer TS version than the root. Either pin everywhere or use caret everywhere.

---

### L5. `@types/express` is exact-pinned while everything else uses caret

**File:** `package.json` line 115
**Severity:** LOW

```json
"@types/express": "4.17.21"
```

No caret/tilde, meaning it won't receive patch updates. This is likely intentional (Express 4 types are stable) but inconsistent with the rest of the dependency strategy.

---

### L6. Potentially unused shadcn UI components

**Severity:** LOW

Multiple shadcn components are installed but never imported outside their own file: `carousel.tsx`, `input-otp.tsx`, `drawer.tsx`, `command.tsx`, `form.tsx`. These ship unused code. While harmless (tree-shaking removes them), they add maintenance burden.

---

### L7. `streamdown` dependency appears unused

**File:** `package.json` line 103
**Severity:** LOW

`"streamdown": "^1.4.0"` is listed in root dependencies but no import of `streamdown` was found in any source file.

---

### L8. Express 4 is in maintenance mode

**File:** `package.json` line 87
**Severity:** LOW

Express 4 (`^4.21.2`) is in maintenance mode. Express 5 has been stable since late 2025. Consider upgrading, though this is not urgent for an internal server.

---

## Notes & Questions

### N1. `COOKIE_NAME` and `ONE_YEAR_MS` shared constants

**File:** `shared/const.ts`

These constants (`COOKIE_NAME = "app_session_id"`, `ONE_YEAR_MS`) suggest session/auth infrastructure that doesn't exist in the server. Is this planned, or leftover?

### N2. Analytics script injection in main.tsx

**File:** `packages/ce-web-client/src/main.tsx` lines 5-22

The client injects a Umami analytics script. This is fine for the docs site but should be documented.

### N3. `pnpm-workspace.yaml` includes `examples/*`

**File:** `pnpm-workspace.yaml` line 3

This means example directories with `package.json` (like `examples/node-basic`, `examples/full-pipeline`, `examples/webhook-telemetry`) are workspace members. This is intentional for examples that depend on workspace packages, but it means `pnpm -r` commands hit examples too.

### N4. No Dockerfile or deployment config

The server is clearly intended for deployment (`NODE_ENV=production` checks, `start` script) but there is no Dockerfile, docker-compose, or deployment configuration.

### N5. `@builder.io/vite-plugin-jsx-loc` purpose unclear

**File:** `vite.config.ts` line 1, `package.json` line 111

This plugin adds source location attributes to JSX elements. It's typically used for visual editors (Builder.io). Unless actively used for debugging, it's unnecessary overhead.

### N6. No `dependabot.yml` entry for pnpm workspace packages

**File:** `.github/dependabot.yml`

Dependabot is configured for the root npm ecosystem and Python, but monorepo packages with their own `package.json` files may not get individual PR updates. Dependabot should handle this via the root config, but it's worth verifying.

---

## Good Patterns

1. **Concurrency control in CI** -- `cancel-in-progress: true` prevents wasted CI minutes on superseded pushes.
2. **Matrix testing** -- Node 18/20/22 and Python 3.10/3.11/3.12 gives good version coverage.
3. **Dependabot configuration** -- Groups dev/prod deps and covers npm, pip, and GitHub Actions.
4. **pnpm overrides for security** -- Root `package.json` patches known vulnerable transitive deps (minimatch, tar, qs, lodash, rollup).
5. **`onlyBuiltDependencies`** -- Explicitly allowlists native deps that need compilation, blocking supply-chain compilation attacks.
6. **Workspace package structure** -- The 4 SDK packages (core, memory, providers, cli) are well-organized with clean dependency chains.
7. **Publish workflow has CI gate** -- Publish requires the full test suite to pass before npm/PyPI publishing.
8. **Proper ESM configuration** -- `"type": "module"` throughout, Node16 module resolution in packages.
9. **Coverage thresholds** -- All package vitest configs enforce 80% statement / 70% branch / 75% function coverage.
10. **Proper `.gitignore`** -- Comprehensive and covers both TS and Python artifacts.

---

## File-by-File Detail

### `packages/ce-web-server/index.ts` (107 lines)

| Line(s) | Issue                                                    | Severity |
| ------- | -------------------------------------------------------- | -------- |
| 30-33   | Rate limiter Map grows unboundedly (C3)                  | CRITICAL |
| 23-25   | CORS defaults broken: `"*"` in dev, `""` in prod (C4)    | CRITICAL |
| 36-46   | No `Access-Control-Allow-Credentials` header             | CRITICAL |
| 52      | `req.ip` unreliable without `trust proxy` (C5)           | CRITICAL |
| 91-96   | No security headers (C2)                                 | CRITICAL |
| 79-81   | No-op `pathRewrite` (M10)                                | MEDIUM   |
| 100-106 | No graceful shutdown (H2)                                | HIGH     |
| 106     | `.catch(console.error)` swallows startup errors silently | LOW      |

### `package.json` (154 lines)

| Line(s)         | Issue                                                  | Severity |
| --------------- | ------------------------------------------------------ | -------- |
| 21-22           | Duplicate `build` / `build:app` scripts (L2)           | LOW      |
| 28              | `test` script runs no tests (C1)                       | CRITICAL |
| 82              | `axios` unused (H3)                                    | HIGH     |
| 103             | `streamdown` unused (L7)                               | LOW      |
| 117             | `@types/google.maps` unused (H4)                       | HIGH     |
| 126             | `pnpm` as devDependency (H7)                           | HIGH     |
| 115             | `@types/express` exact-pinned (L5)                     | LOW      |
| 121-127         | `autoprefixer`/`postcss` possibly unused with TW4 (L3) | LOW      |
| 132 vs packages | TS version pinning inconsistency (L4)                  | LOW      |

### `tsconfig.json` (32 lines)

| Line(s) | Issue                                              | Severity |
| ------- | -------------------------------------------------- | -------- |
| 13      | `downlevelIteration` unnecessary with ES2022 (M3)  | MEDIUM   |
| 17      | `"jsx": "preserve"` suboptimal for Vite (L1)       | LOW      |
| 5       | `shared/**/*` include for vestigial directory (M8) | MEDIUM   |

### `.github/workflows/ci.yml` (91 lines)

| Line(s) | Issue                                | Severity |
| ------- | ------------------------------------ | -------- |
| 39      | `pnpm test` runs no unit tests (C1)  | CRITICAL |
| --      | No coverage reporting step           | MEDIUM   |
| --      | No artifact upload for build outputs | LOW      |

### `.github/workflows/publish.yml` (119 lines)

| Line(s) | Issue                                      | Severity |
| ------- | ------------------------------------------ | -------- |
| 41      | Correctly runs `pnpm test:all`             | OK       |
| --      | Missing lint/format check in CI gate (M11) | MEDIUM   |

### `vite.config.ts` (59 lines)

| Line(s) | Issue                                               | Severity |
| ------- | --------------------------------------------------- | -------- |
| 19      | Dead `@assets` alias to non-existent directory (M2) | MEDIUM   |

### `eslint.config.js` (38 lines)

| Line(s) | Issue                                                      | Severity |
| ------- | ---------------------------------------------------------- | -------- |
| 33-34   | Ignores `client/**` and `server/**` which don't exist (H8) | HIGH     |

### `components.json` (19 lines)

| Line(s) | Issue                                                       | Severity |
| ------- | ----------------------------------------------------------- | -------- |
| 7       | CSS path points to non-existent `client/src/index.css` (M1) | MEDIUM   |

### `schemas/context-item.schema.json` (31 lines)

| Line(s) | Issue                                                  | Severity |
| ------- | ------------------------------------------------------ | -------- |
| 13      | `tokens` should be `"integer"` not `"number"` (M7)     | MEDIUM   |
| --      | Missing `taskId`, `isOutcome`, `dependsOn` fields (M5) | MEDIUM   |

### `schemas/context-pack.schema.json` (30 lines)

| Line(s) | Issue                                      | Severity |
| ------- | ------------------------------------------ | -------- |
| 19, 23  | `$ref: "ContextItem"` is non-standard (M4) | MEDIUM   |

### `schemas/context-trace.schema.json` (32 lines)

| Line(s) | Issue                                      | Severity |
| ------- | ------------------------------------------ | -------- |
| 8       | `$ref: "ContextPack"` is non-standard (M4) | MEDIUM   |

### `schemas/context-plan.schema.json` (25 lines)

| Line(s) | Issue                                      | Severity |
| ------- | ------------------------------------------ | -------- |
| 19      | `$ref: "ContextItem"` is non-standard (M4) | MEDIUM   |

### `schemas/memory-item.schema.json` (17 lines)

| Line(s) | Issue                                                            | Severity |
| ------- | ---------------------------------------------------------------- | -------- |
| --      | Missing `lastAccessedAt`, `isSummary`, `embedding`, `links` (M6) | MEDIUM   |

### `schemas/cache-aware-pack.schema.json` (62 lines)

| Line(s) | Issue                                      | Severity |
| ------- | ------------------------------------------ | -------- |
| 29, 33  | `$ref: "ContextItem"` is non-standard (M4) | MEDIUM   |

### `schemas/pipeline-result.schema.json` (67 lines)

| Line(s)        | Issue                                      | Severity |
| -------------- | ------------------------------------------ | -------- |
| 18, 22, 51, 53 | `$ref: "ContextItem"` is non-standard (M4) | MEDIUM   |

### `schemas/beads-issue.schema.json` (95 lines)

No issues found. Well-structured with proper enums and constraints.

### `schemas/cost-estimate.schema.json` (44 lines)

No issues found. Good use of `"additionalProperties": false`.

### `schemas/webhook-analytics.schema.json` (99 lines)

No issues found. Correctly uses `"integer"` for token counts (unlike context-item schema).

### `shared/const.ts` (2 lines)

Vestigial. See N1.

### `pnpm-workspace.yaml` (3 lines)

See N3 regarding `examples/*`.

### `.prettierrc` (15 lines)

No issues. Consistent and matches the documented convention (double quotes, semicolons, 2-space, 80 chars).

### `.gitignore` (128 lines)

No issues. Comprehensive coverage.

### `.github/dependabot.yml` (25 lines)

No issues. Well-configured.

### `.github/FUNDING.yml` (1 line)

No issues.

### `.github/ISSUE_TEMPLATE/bug_report.yml` (48 lines)

No issues.

### `.github/ISSUE_TEMPLATE/feature_request.yml` (35 lines)

No issues.

### Package `tsconfig.json` files (ce-core, ce-memory, ce-providers, ce-cli)

Consistent. All use ES2020/Node16 properly. `ce-cli` is the only one with `esModuleInterop: true` (needed for Commander).

### Package `vitest.config.ts` files

Consistent coverage thresholds across all packages. Alias resolution is correct.

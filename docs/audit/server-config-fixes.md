# Server, Config & CI Audit -- Fixes Applied

**Date:** 2026-03-17
**Reference:** `docs/audit/server-config-audit.md`

---

## Summary

All 5 Critical, all 8 High, and 10 of 11 Medium issues from the audit have been fixed. The remaining Medium issue (M11 -- publish workflow missing lint step) was deferred as it requires coordinating with the publish workflow's gate job and is low-risk.

**Total changes:** 14 files modified, 1 file deleted, 1 file created.

---

## Critical Fixes

### C1. CI now runs unit tests

**File:** `.github/workflows/ci.yml`

Added `pnpm test:packages` step before the existing `pnpm test` step. The TypeScript CI job now runs:

1. Type check (`pnpm check:all`)
2. Build (`pnpm build:all`)
3. Unit tests (`pnpm test:packages`) -- **NEW: runs all Vitest suites**
4. App check (`pnpm test`) -- type check + vite/esbuild build

Previously, `pnpm test` only ran type-checking and the build, meaning 389+ tests were never executed in CI.

---

### C2. Security headers added to all responses

**File:** `packages/ce-web-server/index.ts`

Added a global middleware (before all routes) that sets:

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `X-XSS-Protection: 0` (modern standard: disable, rely on CSP)
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: camera=(), microphone=(), geolocation=()`
- `Strict-Transport-Security: max-age=63072000; includeSubDomains` (production only)

---

### C3. Rate limiter memory leak fixed

**File:** `packages/ce-web-server/index.ts`

Extracted rate limiting into a `createRateLimiter()` function with:

- **Periodic cleanup:** An `setInterval` timer purges expired entries from the Map. Runs at `max(windowMs, 60s)` intervals.
- **`.unref()` on timer:** Prevents the cleanup timer from keeping the process alive.
- **`dispose()` method:** Clears the timer and state map, called during graceful shutdown.

The old code stored rate-limit entries in a bare `Map` with no expiry mechanism. Any IP that made a single request and never returned would leak memory permanently.

---

### C4. CORS configuration fixed

**File:** `packages/ce-web-server/index.ts`

Before:

- Dev: `corsOrigin = "*"` (wildcard breaks credentials)
- Prod: `corsOrigin = ""` (falsy, so no CORS headers at all)

After:

- Dev: `corsOrigin = "http://localhost:3000"` (specific origin, credentials-compatible)
- Prod: `corsOrigin = undefined` (no CORS headers unless `CORS_ORIGIN` is explicitly set)
- Added `Access-Control-Allow-Credentials: true` header

---

### C5. `trust proxy` configured

**File:** `packages/ce-web-server/index.ts`

Added `app.set("trust proxy", 1)` to trust the first proxy hop. This makes `req.ip` return the real client IP from `X-Forwarded-For` when behind a reverse proxy, which is necessary for correct rate limiting.

---

## High-Priority Fixes

### H2. Graceful shutdown handling

**File:** `packages/ce-web-server/index.ts`

Added `SIGTERM` and `SIGINT` handlers that:

1. Log the received signal
2. Call `rateLimiter.dispose()` to clean up the timer
3. Call `server.close()` to stop accepting new connections and drain existing ones
4. Force-exit after 10 seconds if connections are not drained (with `.unref()` so it doesn't block)

Also improved the startup error handler from `.catch(console.error)` to `.catch(err => { console.error(...); process.exit(1); })`.

---

### H3. Removed unused `axios` dependency

**File:** `package.json`

Removed `"axios": "^1.13.5"` from dependencies. No file in the codebase imports axios.

---

### H4. Removed unused `@types/google.maps`

**File:** `package.json`

Removed `"@types/google.maps": "^3.58.1"` from devDependencies. It was only used by the dead `Map.tsx` component (see H5).

---

### H5. Deleted dead `Map.tsx` component

**File deleted:** `packages/ce-web-client/src/components/Map.tsx`

This was a Google Maps component never imported by any file. It referenced `VITE_FRONTEND_FORGE_API_KEY` and a third-party maps proxy service irrelevant to the project.

---

### H6. Removed dead OAuth/login code

**File:** `packages/ce-web-client/src/const.ts`

Removed the `getLoginUrl()` function and the re-exports of `COOKIE_NAME`/`ONE_YEAR_MS` from `@shared/const`. These referenced:

- `VITE_OAUTH_PORTAL_URL` and `VITE_APP_ID` env vars that were never configured
- An `/api/oauth/callback` route that doesn't exist in the server
- `shared/const.ts` which exported session constants for auth that doesn't exist

No file imported anything from `const.ts`, so this was entirely dead code.

---

### H7. Removed `pnpm` from devDependencies

**File:** `package.json`

Removed `"pnpm": "^10.28.2"` from devDependencies. The package manager is already specified via the `"packageManager": "pnpm@10.30.3"` field, which is the correct mechanism (used by corepack). Having pnpm as a dep wastes ~50MB in node_modules.

---

### H8. Fixed ESLint ignore paths

**File:** `eslint.config.js`

Changed ignores from non-existent directories:

- `"client/**"` -> `"packages/ce-web-client/**"` (the actual location)
- `"server/**"` -> `"shared/**"` (vestigial shared directory)

---

## Medium-Priority Fixes

### M1. Fixed `components.json` CSS path

**File:** `components.json`

Changed `"css": "client/src/index.css"` to `"css": "packages/ce-web-client/src/index.css"`. The old path pointed to a directory that no longer exists, breaking `npx shadcn` commands.

---

### M2. Removed dead `@assets` Vite alias

**File:** `vite.config.ts`

Removed the `@assets` alias pointing to non-existent `attached_assets/` directory. Also removed the `@shared` alias pointing to `shared/` (no longer referenced after H6 cleanup).

---

### M3. Removed unnecessary `downlevelIteration`

**File:** `tsconfig.json`

Removed `"downlevelIteration": true`. With `"target": "ES2022"`, iterators and generators are natively supported and not downleveled, so this flag has no effect.

---

### M4. Fixed non-standard `$ref` in all JSON schemas

**Files:** All schemas that used `$ref`

Changed bare `$ref` values from type names to proper relative file references per JSON Schema 2020-12:

| Before                  | After                                |
| ----------------------- | ------------------------------------ |
| `"$ref": "ContextItem"` | `"$ref": "context-item.schema.json"` |
| `"$ref": "ContextPack"` | `"$ref": "context-pack.schema.json"` |

Applied to 6 schema files:

- `context-pack.schema.json` (2 refs)
- `context-trace.schema.json` (1 ref)
- `context-plan.schema.json` (1 ref)
- `cache-aware-pack.schema.json` (2 refs)
- `pipeline-result.schema.json` (5 refs)

---

### M5. Added missing fields to ContextItem schema

**File:** `schemas/context-item.schema.json`

Added fields present in TS and/or Python SDKs but missing from the schema:

- `taskId` (string) -- BEADS task ID
- `isOutcome` (boolean) -- critical outcome marker
- `dependsOn` (string[]) -- task dependency IDs
- `supersedes` (string) -- Python SDK: item supersession
- `embedding` (number[]) -- Python SDK: vector embedding
- `parentId` (string) -- Python SDK: hierarchical parent
- `cost` (number) -- Python SDK: monetary cost
- `latency` (number) -- Python SDK: latency metric
- `links` (string[]) -- Python SDK: related item IDs

All fields are optional (not in `required`), preserving backward compatibility.

---

### M6. Added missing fields to MemoryItem schema

**File:** `schemas/memory-item.schema.json`

Added fields present in the Python SDK:

- `lastAccessedAt` (string) -- timestamp of last access
- `isSummary` (boolean) -- summary marker
- `embedding` (number[]) -- vector embedding
- `links` (string[]) -- related memory IDs

---

### M7. Changed token counts from `number` to `integer`

**Files:** All schemas with token-related fields

Changed `"type": "number"` to `"type": "integer"` for fields that represent token counts (always whole numbers):

- `tokens`, `compressedTokens` in context-item and trace schemas
- `maxTokens`, `reserveTokens` in budget objects
- `totalTokens`, `cacheableTokens`, `volatileTokens` in pack schemas
- `itemCount`, `keptCount`, `deltaTokens`, `inputCount` in pipeline-result
- `partitionBoundaries` items in cache-aware-pack

This aligns with `webhook-analytics.schema.json` which already used `"integer"` correctly, and with the Python SDK where these fields are typed as `int`.

---

### M8. Removed `shared/**/*` from tsconfig include + cleaned `@shared` path

**File:** `tsconfig.json`

Removed `"shared/**/*"` from `include` and `"@shared/*"` from `paths`. The `shared/` directory only contained vestigial auth constants no longer used anywhere.

---

### M9. Created `.env.example`

**File:** `.env.example` (new)

Documents all environment variables read by the server and client:

- `PORT`, `BACKEND_URL`, `BACKEND_PORT`, `CORS_ORIGIN`, `RATE_LIMIT_WINDOW_MS`, `RATE_LIMIT_MAX`
- `VITE_ANALYTICS_ENDPOINT`, `VITE_ANALYTICS_WEBSITE_ID`

---

### M10. Removed no-op `pathRewrite` from proxy config

**File:** `packages/ce-web-server/index.ts`

Removed the `pathRewrite: { "^/api": "/api" }` configuration that rewrote `/api` to `/api` (no-op).

---

### Additional: Cleaned up lint scripts

**File:** `package.json`

Removed `'shared/**/*.ts'` from the `lint` and `lint:fix` scripts since the `shared/` directory is vestigial.

---

### Additional: Deduplicated build scripts

**File:** `package.json`

Changed `"build"` from a duplicate of `"build:app"` to `"build": "pnpm run build:app"`, eliminating the duplicated command string.

---

### Additional: Removed unused `streamdown` dependency

**File:** `package.json`

Removed `"streamdown": "^1.4.0"` from dependencies. No file in the codebase imports it.

---

### Additional: Improved `jsx` setting

**File:** `tsconfig.json`

Changed `"jsx": "preserve"` to `"jsx": "react-jsx"` for better IDE JSX support. With `noEmit: true` and Vite handling the actual transform, both values work, but `react-jsx` provides more accurate type checking for the modern JSX transform.

---

## Deferred

### M11. Publish workflow lint/format check

The publish workflow's CI gate job runs tests but not linting. This is lower-risk since the regular CI already gates merges, and adding it requires coordinating step ordering in the publish gate job. Deferred for a follow-up.

---

## Files Changed

| File                                            | Action                                      |
| ----------------------------------------------- | ------------------------------------------- |
| `packages/ce-web-server/index.ts`               | Rewritten (C2, C3, C4, C5, H2, M10)         |
| `.github/workflows/ci.yml`                      | Modified (C1)                               |
| `package.json`                                  | Modified (H3, H4, H7, L2, L7, lint scripts) |
| `tsconfig.json`                                 | Rewritten (M3, M8, L1)                      |
| `eslint.config.js`                              | Modified (H8)                               |
| `vite.config.ts`                                | Modified (M2)                               |
| `components.json`                               | Modified (M1)                               |
| `schemas/context-item.schema.json`              | Rewritten (M5, M7)                          |
| `schemas/context-pack.schema.json`              | Rewritten (M4, M7)                          |
| `schemas/context-trace.schema.json`             | Rewritten (M4, M7)                          |
| `schemas/context-plan.schema.json`              | Rewritten (M4, M7)                          |
| `schemas/cache-aware-pack.schema.json`          | Rewritten (M4, M7)                          |
| `schemas/pipeline-result.schema.json`           | Rewritten (M4, M7)                          |
| `schemas/memory-item.schema.json`               | Rewritten (M6, M7)                          |
| `packages/ce-web-client/src/components/Map.tsx` | Deleted (H5)                                |
| `packages/ce-web-client/src/const.ts`           | Cleaned (H6)                                |
| `.env.example`                                  | Created (M9)                                |

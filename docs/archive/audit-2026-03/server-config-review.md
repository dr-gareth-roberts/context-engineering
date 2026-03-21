# Server, Config & CI Audit -- Fix Verification

**Date:** 2026-03-17
**Reviewed:** `docs/audit/server-config-fixes.md` against `docs/audit/server-config-audit.md`
**Verdict:** Fixes are substantively correct. Two issues found and repaired during review.

---

## Issues Found During Review

### R1. Schema `$id` values did not match `$ref` filenames (BROKEN -- fixed)

**Severity:** HIGH (breaks schema validation in both TS and Python CLIs)

The M4 fix changed `$ref` values from bare type names (e.g., `"ContextItem"`) to relative filenames (e.g., `"context-item.schema.json"`), but left `$id` values as the original bare names (`"ContextItem"`, `"ContextPack"`, etc.).

Both CLI implementations resolve `$ref` by looking up schemas by their `$id`:

- **TypeScript (Ajv):** `ajv.addSchema(schema)` registers under `$id`. A `$ref: "context-item.schema.json"` looks up `"context-item.schema.json"` in the registry, but the schema was registered as `"ContextItem"`. Mismatch.
- **Python (jsonschema):** `_load_all_schemas()` stores schemas as `store[schema["$id"]]`. `RefResolver` looks up `$ref` values against the store. Same mismatch.

**Fix applied:** Updated `$id` in all 10 schema files from bare type names to filenames matching their `$ref` usage:

| Schema file                     | Old `$id`          | New `$id`                       |
| ------------------------------- | ------------------ | ------------------------------- |
| `context-item.schema.json`      | `ContextItem`      | `context-item.schema.json`      |
| `context-pack.schema.json`      | `ContextPack`      | `context-pack.schema.json`      |
| `context-trace.schema.json`     | `ContextTrace`     | `context-trace.schema.json`     |
| `context-plan.schema.json`      | `ContextPlan`      | `context-plan.schema.json`      |
| `cache-aware-pack.schema.json`  | `CacheAwarePack`   | `cache-aware-pack.schema.json`  |
| `pipeline-result.schema.json`   | `PipelineResult`   | `pipeline-result.schema.json`   |
| `memory-item.schema.json`       | `MemoryItem`       | `memory-item.schema.json`       |
| `beads-issue.schema.json`       | `BeadsIssue`       | `beads-issue.schema.json`       |
| `cost-estimate.schema.json`     | `CostEstimate`     | `cost-estimate.schema.json`     |
| `webhook-analytics.schema.json` | `WebhookAnalytics` | `webhook-analytics.schema.json` |

---

### R2. `cost-estimate.schema.json` token fields still used `"number"` (incomplete M7 -- fixed)

**Severity:** LOW (schema is less strict than the actual types)

The M7 fix changed token count fields to `"integer"` across most schemas, but missed `cost-estimate.schema.json`. The fields `inputTokens`, `cachedTokens`, `uncachedTokens`, and `outputTokens` are `int` in Python and always whole numbers in TS. They remained `"type": "number"`.

**Fix applied:** Changed these four fields from `"number"` to `"integer"` in `cost-estimate.schema.json`. Dollar amounts (`costWithoutCache`, `costWithCache`, `savings`, `savingsPercent`, `cacheEfficiency`) correctly remain `"number"`.

---

## Critical Fixes -- Verified

### C1. CI now runs unit tests -- PASS

`.github/workflows/ci.yml` line 38-39 adds a `pnpm test:packages` step. This maps to `"test:packages": "pnpm -r test"` in `package.json` line 29, which runs each workspace package's `test` script (Vitest). The step is placed after `Build` and before the existing `pnpm test` (type check + app build). The workflow structure is correct and will execute all 389+ TS tests.

### C2. Security headers -- PASS

`packages/ce-web-server/index.ts` lines 63-79 adds a global middleware setting:

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `X-XSS-Protection: 0` (correct modern standard)
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: camera=(), microphone=(), geolocation=()`
- `Strict-Transport-Security` (production only, correct -- HSTS in dev would break localhost)

Middleware is before all routes (line 63, before `server = createServer(app)` usage). Correct.

### C3. Rate limiter memory leak -- PASS

`createRateLimiter()` (lines 14-53):

- Cleanup interval at `max(windowMs, 60s)` -- reasonable floor.
- Timer uses `.unref()` -- won't keep process alive.
- `dispose()` clears both the interval and the map.
- `dispose()` is called during graceful shutdown (line 167).

The cleanup loop iterates the map and deletes expired entries. This is correct and prevents unbounded growth.

### C4. CORS configuration -- PASS

Lines 94-98:

- Dev default: `"http://localhost:3000"` (specific origin, credentials-compatible).
- Production default: `undefined` (no CORS headers unless explicitly set via `CORS_ORIGIN`).
- `Access-Control-Allow-Credentials: true` header is set (line 116).
- CORS headers are only applied to `/api` routes (line 105), not static files. Correct.

### C5. Trust proxy -- PASS

Line 60: `app.set("trust proxy", 1)` -- trusts exactly one proxy hop. Standard and secure for single-proxy deployments.

---

## High-Priority Fixes -- Verified

### H2. Graceful shutdown -- PASS

Lines 165-180:

- Handles both `SIGTERM` and `SIGINT`.
- Calls `rateLimiter.dispose()` before `server.close()`.
- Force-exit timeout (10s) uses `.unref()` so it doesn't prevent exit if close completes first.
- Startup error handler now calls `process.exit(1)` instead of just logging (line 184-185).

### H3. `axios` removed -- PASS

Not present in `package.json` dependencies or devDependencies.

### H4. `@types/google.maps` removed -- PASS

Not present in `package.json` devDependencies.

### H5. `Map.tsx` deleted -- PASS

`packages/ce-web-client/src/components/Map.tsx` no longer exists (confirmed via glob).

### H6. Dead OAuth code removed -- PASS

`packages/ce-web-client/src/const.ts` contains only a comment stub. No `getLoginUrl`, no `COOKIE_NAME`, no `@shared/const` imports.

### H7. `pnpm` removed from devDependencies -- PASS

Not present in `package.json` devDependencies. `packageManager` field (line 133) correctly handles version enforcement.

### H8. ESLint ignore paths -- PASS

`eslint.config.js` line 33: `"packages/ce-web-client/**"` (replaces old `"client/**"`).
Line 34: `"shared/**"` (replaces old `"server/**"`).

Note: `"server/**"` was replaced with `"shared/**"` rather than `"packages/ce-web-server/**"`. This is correct because the web server TS files ARE linted (they're in the `lint` script glob on `package.json` line 34), while `shared/` is vestigial and should be ignored.

---

## Medium-Priority Fixes -- Verified

### M1. `components.json` CSS path -- PASS

Line 7: `"css": "packages/ce-web-client/src/index.css"`. Correct path.

### M2. Dead Vite aliases removed -- PASS

`vite.config.ts` has no `@assets` or `@shared` alias. Only `@`, `@context-engineering/core`, `@context-engineering/memory`, and `@context-engineering/providers` remain.

### M3. `downlevelIteration` removed -- PASS

Not present in `tsconfig.json`. Target is `ES2022` so this was a no-op.

### M4. `$ref` values updated to filenames -- PASS (with R1 fix)

All `$ref` values now use relative filenames (`"context-item.schema.json"`, `"context-pack.schema.json"`). After R1 fix, `$id` values match. Verified across all 6 schemas that use `$ref`:

- `context-pack.schema.json`: 2 refs to `context-item.schema.json`
- `context-trace.schema.json`: 1 ref to `context-pack.schema.json`
- `context-plan.schema.json`: 1 ref to `context-item.schema.json`
- `cache-aware-pack.schema.json`: 2 refs to `context-item.schema.json`
- `pipeline-result.schema.json`: 4 refs to `context-item.schema.json`

Ref count note: The fix summary says pipeline-result has 5 refs, but the actual file has 4 (lines 18, 22, 53, 58). The count discrepancy in the fix summary is cosmetic only; all actual refs are correct.

### M5. ContextItem schema fields -- PASS

All 9 added fields verified against TS types (`packages/ce-core/src/types.ts`) and Python model (`python/context_engineering/core.py`):

- `taskId`, `isOutcome`, `dependsOn` -- present in both TS and Python
- `supersedes`, `embedding`, `parentId`, `cost`, `latency`, `links` -- Python-only, correctly documented

All are optional (not in `required`).

### M6. MemoryItem schema fields -- PASS

`lastAccessedAt`, `isSummary`, `embedding`, `links` all present and match Python's `MemoryItem` model (`python/context_engineering/memory.py` lines 31-37).

### M7. Token counts as `integer` -- PASS (with R2 fix)

Verified across all schemas. After R2 fix, `cost-estimate.schema.json` token fields are also `integer`. Fields that are genuinely floating-point (scores, percentages, dollar costs, ratios) remain `number`.

### M8. `shared/**/*` and `@shared/*` removed from tsconfig -- PASS

`tsconfig.json` `include` has only `packages/ce-web-client/src/**/*` and `packages/ce-web-server/**/*.ts`. No `shared` references in `paths`.

### M9. `.env.example` created -- PASS

Documents all server env vars (`PORT`, `BACKEND_URL`, `BACKEND_PORT`, `CORS_ORIGIN`, `RATE_LIMIT_WINDOW_MS`, `RATE_LIMIT_MAX`) and client env vars (`VITE_ANALYTICS_ENDPOINT`, `VITE_ANALYTICS_WEBSITE_ID`). Correctly omits the dead OAuth vars that were removed in H6.

### M10. No-op `pathRewrite` removed -- PASS

`createProxyMiddleware()` call (lines 138-141) has only `target` and `changeOrigin`. No `pathRewrite`.

---

## Additional Fixes -- Verified

### Build script dedup -- PASS

`package.json` line 22: `"build": "pnpm run build:app"` delegates to `build:app` instead of duplicating the command.

### Lint script cleanup -- PASS

`package.json` lines 34-35: `lint` and `lint:fix` no longer reference `shared/**/*.ts`.

### `streamdown` removed -- PASS

Not present in `package.json` dependencies.

### JSX setting updated -- PASS

`tsconfig.json` line 15: `"jsx": "react-jsx"`. Correct for modern React JSX transform.

---

## Summary

| Category                       | Count | Status                                       |
| ------------------------------ | ----- | -------------------------------------------- |
| Critical (C1-C5)               | 5     | All verified correct                         |
| High (H2-H8)                   | 7     | All verified correct                         |
| Medium (M1-M10)                | 10    | All verified correct (2 had gaps, now fixed) |
| Additional                     | 4     | All verified correct                         |
| **Issues found during review** | **2** | **Both fixed (R1, R2)**                      |
| Deferred (M11)                 | 1     | Acknowledged                                 |

### Files Modified During Review

| File                                    | Change                                            |
| --------------------------------------- | ------------------------------------------------- |
| `schemas/context-item.schema.json`      | `$id` updated to match `$ref` convention          |
| `schemas/context-pack.schema.json`      | `$id` updated                                     |
| `schemas/context-trace.schema.json`     | `$id` updated                                     |
| `schemas/context-plan.schema.json`      | `$id` updated                                     |
| `schemas/cache-aware-pack.schema.json`  | `$id` updated                                     |
| `schemas/pipeline-result.schema.json`   | `$id` updated                                     |
| `schemas/memory-item.schema.json`       | `$id` updated                                     |
| `schemas/beads-issue.schema.json`       | `$id` updated                                     |
| `schemas/cost-estimate.schema.json`     | `$id` updated + token fields changed to `integer` |
| `schemas/webhook-analytics.schema.json` | `$id` updated                                     |

# Web Client Deep Audit

**Scope:** `packages/ce-web-client/src/` -- React 19 docs + demos web app
**Date:** 2026-03-17
**Auditor:** Automated code review (Claude)

---

## Summary

The web client is a single-page marketing/documentation site built with React 19, Tailwind CSS 4, shadcn/ui, wouter, and framer-motion. The codebase has a significant scaffolding-to-usage ratio problem: dozens of UI components are installed but never used, and several custom components (Map, MermaidDiagram, Quiz, ProgressTracker, Resources, SearchModal) exist as dead code. The active code in `Home.tsx` and `CausalPlayground.tsx` has real bugs (broken Sonner import, unhandled promise rejections, highlight.js mutation issues), accessibility gaps, and a security concern with unescaped HTML injection in MermaidDiagram. The `const.ts` file imports from a shared module that exposes OAuth constants never used in any active code path.

**Files audited:** 68 source files (6 pages/components, 6 hooks/contexts/lib, ~50 UI primitives, 1 CSS file, 1 HTML file)

---

## Critical Issues

### C1. Sonner Toaster imports from `next-themes` -- will crash at runtime

**File:** `src/components/ui/sonner.tsx`, line 1
**Severity:** CRITICAL

```tsx
import { useTheme } from "next-themes";
```

This app is NOT a Next.js app -- it is a Vite/React SPA. The `next-themes` package depends on Next.js internals and its `useTheme` hook will either throw or return `undefined` at runtime. The Toaster is rendered in `App.tsx` line 30, so this crashes the entire app unless `next-themes` happens to degrade gracefully in a non-Next environment.

**Fix:** Replace with the app's own `useTheme` from `@/contexts/ThemeContext` or remove the theme integration from Sonner.

### C2. `const.ts` imports from `@shared/const` -- OAuth scaffolding with no consumer

**File:** `src/const.ts`, lines 1-17
**Severity:** CRITICAL (build breakage risk + dead code security concern)

```ts
export { COOKIE_NAME, ONE_YEAR_MS } from "@shared/const";

export const getLoginUrl = () => {
  const oauthPortalUrl = import.meta.env.VITE_OAUTH_PORTAL_URL;
  const appId = import.meta.env.VITE_APP_ID;
  ...
```

- `COOKIE_NAME` and `ONE_YEAR_MS` are re-exported but never imported anywhere in the web client.
- `getLoginUrl()` constructs OAuth URLs using env vars (`VITE_OAUTH_PORTAL_URL`, `VITE_APP_ID`) that are never documented and unlikely to be set.
- The `@shared/const` path alias resolves via tsconfig but the import will fail at Vite build time if the alias is not also configured in `vite.config`.
- This entire file is dead code -- no file in the web client imports from it.

### C3. `highlight.js` double-mutation bug in CodeBlock

**File:** `src/components/CodeBlock.tsx`, lines 32-36
**Severity:** CRITICAL (visual corruption)

```tsx
useEffect(() => {
  if (codeRef.current && language !== "text") {
    hljs.highlightElement(codeRef.current);
  }
}, [code, language]);
```

`hljs.highlightElement()` mutates the DOM element in place. When `code` changes, React re-renders and sets the `textContent`, but hljs has already replaced it with highlighted spans. On subsequent renders, hljs re-highlights already-highlighted HTML, causing double-encoding and garbled output. The correct approach is to use `hljs.highlight(code, { language })` and set the result via state, or use a `key` prop to force remount.

---

## High Priority

### H1. Unhandled promise rejection in `CodeBlock.handleCopy`

**File:** `src/components/CodeBlock.tsx`, line 38-41
**Severity:** HIGH

```tsx
const handleCopy = async () => {
  await navigator.clipboard.writeText(code);
  setCopied(true);
  setTimeout(() => setCopied(false), 2000);
};
```

No try/catch. `navigator.clipboard.writeText` throws if:

- The page is not served over HTTPS (common in development)
- The document is not focused
- Clipboard permissions are denied

This will produce an unhandled promise rejection.

### H2. Unescaped HTML injection with mermaid SVG output -- XSS surface

**File:** `src/components/MermaidDiagram.tsx`, line 92
**Severity:** HIGH

The component sets SVG content from Mermaid rendering directly into the DOM without sanitization. Mermaid's `render()` can produce arbitrary SVG including `<script>` elements or event handlers if the chart definition is user-controlled. While the current usage only passes static strings from the `diagrams` object, the component accepts `chart` as a prop. Any future use with user input is a direct XSS vector. The SVG output should be sanitized with DOMPurify or equivalent before injection.

### H3. Massive dead component inventory -- 5 full components never imported

**Files:**

- `src/components/Map.tsx` -- Google Maps integration (never imported)
- `src/components/MermaidDiagram.tsx` -- Mermaid rendering (never imported)
- `src/components/Quiz.tsx` -- Quiz component (never imported)
- `src/components/ProgressTracker.tsx` -- Progress tracking (never imported)
- `src/components/Resources.tsx` -- Resources list (never imported)
- `src/components/SearchModal.tsx` -- Search overlay (never imported)

**Severity:** HIGH (maintenance burden, bundle size)

These components add hundreds of lines of dead code. Worse, they pull in heavy dependencies at build time:

- `Map.tsx` loads Google Maps API via script injection
- `MermaidDiagram.tsx` imports the full `mermaid` library (~2.5MB)
- `SearchModal.tsx` has its own keyboard handler that could conflict

### H4. ~40 unused shadcn/ui component files

**Severity:** HIGH (bundle size, dependency bloat)

The following UI components in `src/components/ui/` are never imported by any active component:

`accordion`, `alert-dialog`, `alert`, `aspect-ratio`, `avatar`, `badge`, `breadcrumb`, `button-group`, `calendar`, `carousel`, `chart`, `checkbox`, `collapsible`, `command`, `context-menu`, `drawer`, `dropdown-menu`, `empty`, `field`, `form`, `hover-card`, `input-group`, `input-otp`, `item`, `kbd`, `label`, `menubar`, `navigation-menu`, `pagination`, `popover`, `progress`, `radio-group`, `resizable`, `scroll-area`, `select`, `separator`, `sheet`, `sidebar`, `skeleton`, `slider`, `spinner`, `switch`, `table`, `tabs`, `toggle-group`, `toggle`

Some are only referenced by other unused components (sidebar uses sheet/skeleton/separator). This is a massive dependency surface -- the `package.json` lists 25+ Radix UI packages for components that are never rendered.

### H5. `useProgress` hook writes to localStorage on every render cycle

**File:** `src/hooks/useProgress.ts`, lines 41-47
**Severity:** HIGH

```tsx
useEffect(() => {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(progress));
  } catch (error) {
    console.error("Failed to save progress:", error);
  }
}, [progress]);
```

Combined with the load effect on lines 28-38, this creates a write-on-mount problem: the initial state (`defaultProgress`) triggers the save effect before the load effect reads from localStorage, potentially overwriting saved data with defaults. The save effect should skip if the data has not been loaded yet.

Note: This hook is only used by the dead `ProgressTracker` component, but the pattern is buggy.

### H6. Missing `htmlFor` on all `<label>` elements

**Files:** `src/pages/Home.tsx` lines 509, 520; `src/components/CausalPlayground.tsx` lines 93, 102, 106
**Severity:** HIGH (accessibility)

All `<label>` elements lack `htmlFor` attributes (or wrapping of their inputs), making them non-functional for screen readers and click-to-focus behavior.

```tsx
<label className="text-[10px] font-bold marker-black uppercase ml-1">
  Budget A (Tokens)
</label>
<Input type="number" ... />
```

---

## Medium Priority

### M1. `"use client"` directives in a Vite SPA

**Files:** `src/components/ui/sheet.tsx`, `sidebar.tsx`, `form.tsx`, `command.tsx`, `toggle-group.tsx`
**Severity:** MEDIUM

These files start with `"use client"` which is a Next.js RSC directive and has no meaning in a Vite app. It is harmless but misleading and suggests copy-paste from a Next.js template.

### M2. Google Maps component exposes API key in client bundle

**File:** `src/components/Map.tsx`, line 89
**Severity:** MEDIUM (security, but component is dead code)

```tsx
const API_KEY = import.meta.env.VITE_FRONTEND_FORGE_API_KEY;
```

API keys prefixed with `VITE_` are embedded in the client bundle. While this is the expected pattern for Maps, the component also references a proxy URL suggesting this might be a private key. Dead code, but risky if revived.

### M3. `loadMapScript` never rejects its promise

**File:** `src/components/Map.tsx`, lines 96-110
**Severity:** MEDIUM

```tsx
function loadMapScript() {
  return new Promise(resolve => {
    ...
    script.onerror = () => {
      console.error("Failed to load Google Maps script");
    };
    ...
  });
}
```

On script load failure, the promise never resolves or rejects, leaving `init()` hanging forever. Should call `reject()` in the `onerror` handler.

### M4. MermaidDiagram `containerRef` serves no purpose after SVG is in state

**File:** `src/components/MermaidDiagram.tsx`, lines 37, 43
**Severity:** MEDIUM (dead ref)

The `containerRef` is checked before rendering (`if (containerRef.current)`) but the SVG is set via state and DOM injection, never through the ref. The ref guard is a no-op after the first render since the div is always mounted.

### M5. Mermaid diagram IDs use `Math.random()` -- not stable across renders

**File:** `src/components/MermaidDiagram.tsx`, line 45
**Severity:** MEDIUM

```tsx
const id = `mermaid-${Math.random().toString(36).substr(2, 9)}`;
```

Each render generates a new random ID. In React Strict Mode (development), this causes double-rendering and orphaned SVG elements. Should use `useId()` or `useMemo`.

### M6. Quiz component uses hardcoded colors that do not respect dark mode

**File:** `src/components/Quiz.tsx` (multiple lines)
**Severity:** MEDIUM

Uses `text-gray-700`, `text-gray-900`, `bg-green-50`, `bg-red-50`, `bg-blue-50`, `bg-white`, `border-gray-300` etc. throughout. These are Tailwind static colors that will not adapt to the dark theme. Should use semantic tokens (`text-foreground`, `bg-card`, etc.).

### M7. ProgressTracker and Resources also use hardcoded colors

**Files:** `src/components/ProgressTracker.tsx`, `src/components/Resources.tsx`
**Severity:** MEDIUM

Same issue as M6 -- `text-gray-700`, `bg-blue-50`, `bg-green-50`, `border-gray-300`, `bg-white` will not adapt to dark mode.

### M8. NotFound page uses hardcoded colors, inconsistent with app theme

**File:** `src/pages/NotFound.tsx`
**Severity:** MEDIUM

Uses `bg-gradient-to-br from-slate-50 to-slate-100`, `bg-white/80`, `text-slate-900`, `bg-blue-600`. This page ignores the whiteboard design system and dark mode entirely.

### M9. `SearchModal.highlightMatch` uses `regex.test()` after `split()` -- consumes regex state

**File:** `src/components/SearchModal.tsx`, lines 314-331
**Severity:** MEDIUM

```tsx
const regex = new RegExp(`(${...})`, "gi");
const parts = text.split(regex);
return parts.map((part, i) =>
  regex.test(part) ? ( ... ) : ( part )
);
```

The `gi` flag creates a stateful regex. `regex.test()` advances `lastIndex`, which means alternating parts will incorrectly fail the test. Using `i` flag without `g` would fix this, or comparing case-insensitively without regex state.

### M10. Home.tsx "Local Repo" button is non-functional

**File:** `src/pages/Home.tsx`, lines 171-173
**Severity:** MEDIUM

```tsx
<Button className="bg-marker-black ...">
  <Github className="w-4 h-4 mr-2" /> Local Repo
</Button>
```

This button has no `onClick` handler and no `href` (it is not wrapped in `asChild` with an `<a>`). It renders as a clickable button that does nothing.

### M11. `EmptyDescription` component type mismatch

**File:** `src/components/ui/empty.tsx`, line 71
**Severity:** MEDIUM

```tsx
function EmptyDescription({ className, ...props }: React.ComponentProps<"p">) {
  return (
    <div ...
```

Props are typed as `<p>` but the rendered element is `<div>`. While functionally similar, this is a type lie.

---

## Low Priority

### L1. `parseItems` does not validate item shape

**File:** `src/pages/Home.tsx`, lines 68-83
**Severity:** LOW

```tsx
if (Array.isArray(parsed)) return { items: parsed };
```

The parsed JSON is cast to `ContextItem[]` without validating that each element actually has `id`, `content`, etc. Invalid shapes will cause runtime errors in `pack()`. Given this is a playground with user-editable JSON, validation would improve UX.

### L2. No `<StrictMode>` wrapper

**File:** `src/main.tsx`, line 31
**Severity:** LOW

```tsx
createRoot(rootElement).render(<App />);
```

React 19's `StrictMode` is not used. This means double-render checks for effect cleanup bugs will not fire during development.

### L3. `index.html` missing `<meta>` for `theme-color` and favicon

**File:** `index.html`
**Severity:** LOW

No `<link rel="icon">` and no `<meta name="theme-color">`. Browsers will show default icons and mobile browser chrome will not match the app's color scheme.

### L4. `usePersistFn` updates ref during render

**File:** `src/hooks/usePersistFn.ts`, line 10
**Severity:** LOW

```tsx
const fnRef = useRef<T>(fn);
fnRef.current = fn; // Mutation during render
```

In React 19, ref mutations during render are a known anti-pattern that can cause issues with concurrent features. The React team recommends updating refs in effects. This is a widely-used pattern (ahooks uses it), but worth noting.

### L5. `useIsMobile` returns `false` during SSR/first render

**File:** `src/hooks/useMobile.tsx`, line 21
**Severity:** LOW

```tsx
return !!isMobile;
```

Initial state is `undefined`, so `!!undefined` returns `false`. This means the first render always assumes desktop. In a Vite SPA this is generally fine, but causes a flash if the viewport is actually mobile.

### L6. No error boundary around CausalPlayground

**File:** `src/pages/Home.tsx`, line 461
**Severity:** LOW

`CausalPlayground` calls `createContextManager` and `JSON.parse` in a `useMemo`. While there is a try/catch, if the import from `@context-engineering/core` fails or throws synchronously during module evaluation, the whole page crashes. An error boundary around just this section would be more resilient.

### L7. Playground labels not associated with inputs via id

**File:** `src/components/CausalPlayground.tsx`
**Severity:** LOW

All labels use `<label>` but none have `htmlFor` to associate with their inputs. Same issue as H6 but in a different component.

### L8. Font loading is render-blocking

**File:** `index.html`, lines 14-19
**Severity:** LOW

Three Google Fonts families are loaded synchronously with `preconnect` but no `font-display: optional` or `swap` fallback. The CSS file includes `display=swap` which mitigates this, but the connection overhead remains on slow networks.

### L9. Custom scrollbar styles only target WebKit browsers

**File:** `src/index.css`, lines 292-307
**Severity:** LOW

`::-webkit-scrollbar` styles do not apply in Firefox. Consider adding `scrollbar-width: thin; scrollbar-color: #b2bec3 #f1f3f4;` for Firefox support.

### L10. Dark mode scrollbar colors are hardcoded to light theme

**File:** `src/index.css`, lines 296-307
**Severity:** LOW

The scrollbar track (`#f1f3f4`) and thumb (`#b2bec3`) colors do not change in dark mode, creating a visual mismatch.

---

## Notes & Questions

### N1. Is the `@shared/const` import path configured in Vite?

The `tsconfig.json` maps `@shared/*` to `./shared/*`, but Vite needs its own alias configuration. If there is no `vite.config.ts` (none was found in the web-client package), this import will fail at build time.

### N2. Why is `next-themes` in dependencies?

The `package.json` lists `"next-themes": "^0.4.6"` as a dependency. This is only used in `sonner.tsx` and is wrong for a Vite app. It should be removed.

### N3. The package.json is at the monorepo root, not in the web-client package

There is no `packages/ce-web-client/package.json` visible in the file listing. The root `package.json` contains all dependencies including Radix UI, Framer Motion, Mermaid, etc. This means ALL packages in the monorepo share these frontend dependencies.

### N4. `vite.config.ts` is missing from the web-client package

No Vite config file was found in `packages/ce-web-client/`. The root `package.json` has `vite` scripts, suggesting the config might be at the monorepo root.

### N5. Router has an explicit `/404` route that is redundant

**File:** `src/App.tsx`, line 13

```tsx
<Route path={"/404"} component={NotFound} />
```

The catch-all `<Route component={NotFound} />` already handles all unmatched routes. The explicit `/404` route is unnecessary unless something programmatically navigates to `/404`.

---

## Good Patterns

1. **ErrorBoundary at the app root** (`App.tsx` line 27) -- catches render errors globally and shows a recovery UI with stack trace.

2. **ThemeProvider with localStorage persistence** (`ThemeContext.tsx`) -- clean implementation with proper `switchable` toggle support. The `useTheme` hook throws when used outside provider, which is correct.

3. **`usePersistFn` for stable callbacks** (`usePersistFn.ts`) -- avoids stale closures without the cognitive overhead of `useCallback` dependency arrays. Common pattern from ahooks.

4. **IME composition handling** in `Input` and `Textarea` -- proper handling of CJK input method editors with Safari workarounds. The `useComposition` hook and `DialogCompositionContext` prevent accidental dialog dismissal during composition.

5. **`useMemo` for derived state** in `Home.tsx` -- `parseItems`, `packA`, `packB`, and `packDiff` are all correctly memoized with proper dependency arrays.

6. **Semantic color tokens** in `index.css` -- the CSS custom property system with light/dark variants is well-organized, using meaningful names like `--marker-blue`, `--highlight-yellow`.

7. **Print stylesheet** (`index.css` lines 310-417) -- comprehensive print styles for PDF generation, including page break controls and whiteboard-card cleanup.

8. **Copy button with aria-label** in `CodeBlock.tsx` -- the copy button has `aria-label="Copy code"`, which is good accessibility practice.

9. **`parseItems` error handling** -- gracefully handles both array and `{ items: [] }` shapes, with clear error messages.

10. **Navigation uses hash links** with `scroll-mt-24` classes on sections for proper offset with sticky header.

---

## File-by-File Detail

### `index.html`

- Missing favicon link
- Missing `theme-color` meta
- `maximum-scale=1` restricts pinch-to-zoom accessibility (L)

### `src/main.tsx`

- Analytics script injection is well-guarded with early returns
- No `<StrictMode>` wrapper (L2)
- Root element null check is correct

### `src/App.tsx`

- Clean component tree with ErrorBoundary > ThemeProvider > TooltipProvider
- Redundant `/404` route (N5)
- Comment about theme is helpful

### `src/const.ts`

- Entirely dead code (C2)
- OAuth scaffolding that is never used and may not build

### `src/index.css`

- Well-structured with Tailwind v4 syntax
- Hardcoded scrollbar colors do not adapt to dark mode (L10)
- Firefox scrollbar not styled (L9)
- Good print styles

### `src/lib/utils.ts`

- Standard `cn()` utility, no issues

### `src/pages/Home.tsx` (680 lines)

- **Line 2:** `motion` imported from `framer-motion` -- heavy dependency for basic fade animations
- **Lines 68-83:** `parseItems` does not validate item shape (L1)
- **Lines 93-117:** `packA`/`packB` useMemo is correct but silently swallows all errors (catch returns null)
- **Lines 509, 520:** Labels missing `htmlFor` (H6)
- **Line 169:** Theme toggle uses emoji which may render differently across platforms
- **Line 171-173:** "Local Repo" button has no `onClick` or `href` -- it does nothing (M10)

### `src/pages/NotFound.tsx`

- Hardcoded non-theme colors (M8)
- Clean and functional otherwise

### `src/contexts/ThemeContext.tsx`

- Clean implementation, no issues

### `src/components/ErrorBoundary.tsx`

- Missing `componentDidCatch` for error logging (minor)
- Shows stack trace to users -- acceptable for dev tools, risky for production

### `src/components/CausalPlayground.tsx`

- **Line 60:** `JSON.parse(beadsJson) as BeadsIssue[]` -- unchecked cast
- **Line 63:** `tokenEstimator: (text) => text.length / 4` -- reasonable heuristic
- **Line 70:** `history.forEach(turn => ctx.addTurn(turn))` -- creates new array ref on every call
- **Line 155:** Uses array index as key (`key={i}`) for a list that can be reordered/mutated -- React reconciliation issue
- **Labels** missing `htmlFor` (L7)

### `src/components/CodeBlock.tsx`

- **Lines 32-36:** hljs double-mutation bug (C3)
- **Lines 38-41:** Unhandled clipboard promise rejection (H1)
- **Line 69:** `className={`language-${language}`}` -- hljs language class is correct

### `src/components/Map.tsx`

- Dead code (H3)
- Promise never rejects on error (M3)
- API key in client bundle (M2)
- `window.google` could be undefined if script fails -- no null check on line 134

### `src/components/MermaidDiagram.tsx`

- Dead code (H3)
- Unescaped HTML injection XSS risk (H2)
- Random ID generation (M5)
- Dead ref (M4)
- `isFullscreen` state uses no `Escape` key handler to exit fullscreen

### `src/components/Quiz.tsx`

- Dead code (H3)
- **Line 162:** Default parameter `= {}` on component props is suspicious -- `QuizProps` has `onComplete?` which is already optional
- Hardcoded colors (M6)
- `calculateScore` called twice when showing results (line 172 + 197) -- minor inefficiency

### `src/components/ProgressTracker.tsx`

- Dead code (H3)
- Hardcoded colors (M7)
- Uses `useProgress` which has the write-on-mount bug (H5)

### `src/components/Resources.tsx`

- Dead code (H3)
- Hardcoded colors (M7)
- Link with `url: "#"` on line 72 -- placeholder that was never filled in

### `src/components/SearchModal.tsx`

- Dead code (H3)
- Regex state bug in `highlightMatch` (M9)
- Good keyboard navigation implementation
- `SearchButton` has `onClick` in dependency array of `useEffect` -- could cause re-registration if parent does not memoize

### `src/hooks/useComposition.ts`

- Comments in Chinese (lines 50, 60) -- inconsistent with English codebase
- Well-implemented Safari workaround

### `src/hooks/useMobile.tsx`

- `.tsx` extension but no JSX -- should be `.ts`
- Returns `false` before hydration (L5)

### `src/hooks/useProgress.ts`

- Write-on-mount race condition (H5)
- Only used by dead `ProgressTracker`

### `src/hooks/usePersistFn.ts`

- Ref mutation during render (L4)
- Solid implementation otherwise

### `src/components/ui/sonner.tsx`

- **CRITICAL:** Imports from `next-themes` (C1)

### `src/components/ui/dialog.tsx`

- Excellent IME composition handling
- Clean context-based composition state tracking

### `src/components/ui/input.tsx` and `textarea.tsx`

- Good IME handling
- Depend on `useDialogComposition` which returns no-op defaults when outside Dialog

### `src/components/ui/empty.tsx`

- Type mismatch: `EmptyDescription` typed as `<p>` but renders `<div>` (M11)

### All other `src/components/ui/*.tsx` files

- Standard shadcn/ui components, well-implemented
- None are used in active code paths

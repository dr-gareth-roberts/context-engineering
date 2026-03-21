# Web Client Audit Fixes

**Date:** 2026-03-17
**Scope:** All Critical, High, and practical Medium issues from `web-client-audit.md`

---

## Summary

68 source files reduced to 20. Removed 48 dead files (6 custom components, 2 hooks, 40 UI primitives). Fixed 3 critical bugs, 6 high-priority issues, and 6 medium-priority issues. No new dependencies added; one dependency (`next-themes`) is now unused and can be removed from `package.json`.

---

## Critical Fixes

### C1. Sonner Toaster -- replaced `next-themes` import with app's own ThemeContext

**File:** `src/components/ui/sonner.tsx`

Changed `import { useTheme } from "next-themes"` to `import { useTheme } from "@/contexts/ThemeContext"`. The app already has a working `ThemeProvider` with a `useTheme` hook that returns `{ theme: "light" | "dark" }`. The Sonner component now reads the theme from the same source as the rest of the app.

The `next-themes` package in `package.json` is now unused and should be removed at the next dependency cleanup.

### C2. Dead OAuth scaffolding in `const.ts` removed

**File:** `src/const.ts`

Removed the `@shared/const` import and `getLoginUrl()` function. No file in the web client imported from `const.ts`, and the `@shared/const` path alias was likely to break Vite builds. The file now contains only a placeholder comment.

### C3. highlight.js double-mutation bug fixed in CodeBlock

**File:** `src/components/CodeBlock.tsx`

**Before:** Used `useEffect` + `hljs.highlightElement(codeRef.current)` which mutates the DOM in-place. When `code` changed, React would re-render the text content, then hljs would re-highlight the already-highlighted spans, causing garbled output.

**After:** Uses `useMemo` + `hljs.highlight(code, { language })` to produce an HTML string, then renders it via a `<span>` element. This is safe because hljs processes plain-text code into `<span>` syntax tokens -- no user-supplied HTML passes through. The `useEffect` and `useRef` imports were removed.

---

## High-Priority Fixes

### H1. Unhandled promise rejection in clipboard copy

**File:** `src/components/CodeBlock.tsx`, `handleCopy()`

Wrapped `navigator.clipboard.writeText()` in try/catch. The Clipboard API throws when the page is not served over HTTPS, the document is not focused, or permissions are denied. The button now silently degrades rather than producing an unhandled rejection.

### H2. XSS surface in MermaidDiagram

**Resolution:** File deleted as part of H3. The component was never imported by any active code. If revived in the future, the SVG output from `mermaid.render()` must be sanitized with DOMPurify before injection.

### H3. Removed 6 dead custom components

**Deleted files:**

- `src/components/Map.tsx` -- Google Maps integration, never imported
- `src/components/MermaidDiagram.tsx` -- Mermaid rendering, never imported
- `src/components/Quiz.tsx` -- Quiz component, never imported
- `src/components/ProgressTracker.tsx` -- Progress tracking, never imported
- `src/components/Resources.tsx` -- Resource links, never imported
- `src/components/SearchModal.tsx` -- Search overlay, never imported

These components added hundreds of lines of dead code and pulled in heavy dependencies (mermaid at ~2.5MB, Google Maps API script injection).

### H4. Removed 40+ unused shadcn/ui component files

**Deleted files (all in `src/components/ui/`):**

accordion, alert-dialog, alert, aspect-ratio, avatar, badge, breadcrumb, button-group, calendar, carousel, chart, checkbox, collapsible, command, context-menu, drawer, dropdown-menu, empty, field, form, hover-card, input-group, input-otp, item, kbd, label, menubar, navigation-menu, pagination, popover, progress, radio-group, resizable, scroll-area, select, separator, sheet, sidebar, skeleton, slider, spinner, switch, table, tabs, toggle-group, toggle

**Kept (actively used):** button, card, dialog, input, textarea, sonner, tooltip

This also removed all `"use client"` directives from the codebase (M1), since they were in the deleted files (sheet, sidebar, form, command, toggle-group).

The corresponding Radix UI packages in `package.json` are now unused and should be cleaned up. The following root `package.json` dependencies are candidates for removal:

```
@radix-ui/react-accordion, @radix-ui/react-alert-dialog, @radix-ui/react-aspect-ratio,
@radix-ui/react-avatar, @radix-ui/react-checkbox, @radix-ui/react-collapsible,
@radix-ui/react-context-menu, @radix-ui/react-dropdown-menu, @radix-ui/react-hover-card,
@radix-ui/react-label, @radix-ui/react-menubar, @radix-ui/react-navigation-menu,
@radix-ui/react-popover, @radix-ui/react-progress, @radix-ui/react-radio-group,
@radix-ui/react-scroll-area, @radix-ui/react-select, @radix-ui/react-separator,
@radix-ui/react-slider, @radix-ui/react-switch, @radix-ui/react-tabs,
@radix-ui/react-toggle, @radix-ui/react-toggle-group,
@hookform/resolvers, cmdk, embla-carousel-react, input-otp,
mermaid, next-themes, react-day-picker, react-hook-form,
react-resizable-panels, recharts, vaul
```

(Not removed from `package.json` in this change to avoid breaking other workspace packages that might share these dependencies.)

### H5. `useProgress` localStorage race condition

**Resolution:** File deleted as part of H3 cleanup. The hook was only used by the dead `ProgressTracker` component. If rebuilt, the fix is to add a `loaded` ref that guards the save effect from firing before the load effect completes.

### H6. Missing `htmlFor` on all labels

**Files:** `src/pages/Home.tsx`, `src/components/CausalPlayground.tsx`

Added `htmlFor` attributes to all `<label>` elements and corresponding `id` attributes to their inputs:

- Home.tsx: `budget-a`, `budget-b`
- CausalPlayground.tsx: `beads-graph`, `token-budget`, `active-task-id`

Also added `aria-label="Task assignment"` to the `<select>` element in CausalPlayground.

---

## Medium-Priority Fixes

### M1. Removed `"use client"` directives

All files containing `"use client"` (sheet, sidebar, form, command, toggle-group) were deleted as part of H4. No remaining files have this directive.

### M8. NotFound page -- hardcoded colors replaced with theme tokens

**File:** `src/pages/NotFound.tsx`

Replaced all hardcoded Tailwind colors with semantic tokens:

- `bg-gradient-to-br from-slate-50 to-slate-100` -> `bg-background`
- `bg-white/80` -> `bg-card/80`
- `bg-red-100` -> `bg-destructive/10`
- `text-red-500` -> `text-destructive`
- `text-slate-900` -> `text-foreground`
- `text-slate-700` -> `text-foreground/80`
- `text-slate-600` -> `text-muted-foreground`
- `bg-blue-600 hover:bg-blue-700 text-white` -> `bg-primary hover:bg-primary/90 text-primary-foreground`

The page now respects dark mode.

### M6/M7. Quiz, ProgressTracker, Resources hardcoded colors

**Resolution:** Files deleted as part of H3. All hardcoded color issues in dead components are gone.

### M9. SearchModal regex state bug

**Resolution:** File deleted as part of H3.

### M10. Non-functional "Local Repo" button in Home.tsx

**File:** `src/pages/Home.tsx`

The button had no `onClick` or `href`. Changed it to a link button using `asChild` + `<a>` that opens the GitHub repository in a new tab with `rel="noopener noreferrer"`. Also renamed the label from "Local Repo" to "GitHub" since it links to a remote URL.

### N5. Removed redundant `/404` route

**File:** `src/App.tsx`

Removed `<Route path={"/404"} component={NotFound} />`. The catch-all `<Route component={NotFound} />` already handles all unmatched routes.

---

## Additional Cleanups

### L9/L10. Scrollbar styles -- Firefox support + dark mode

**File:** `src/index.css`

- Replaced hardcoded scrollbar colors (`#f1f3f4`, `#b2bec3`, `#636e72`) with CSS custom properties (`var(--muted)`, `var(--muted-foreground)`, `var(--foreground)`) so they adapt to dark mode.
- Added Firefox scrollbar support via `scrollbar-width: thin` and `scrollbar-color`.

### Chinese comments translated to English

**File:** `src/hooks/useComposition.ts`

Two comments in Chinese were replaced with English equivalents for codebase consistency.

### Dead hooks removed

**Deleted:**

- `src/hooks/useProgress.ts` -- only used by dead ProgressTracker
- `src/hooks/useMobile.tsx` -- never imported by any file

---

## File Count

| Category                                                                | Before | After                                                      |
| ----------------------------------------------------------------------- | ------ | ---------------------------------------------------------- |
| Custom components                                                       | 8      | 2 (CodeBlock, CausalPlayground)                            |
| Pages                                                                   | 2      | 2 (Home, NotFound)                                         |
| UI primitives                                                           | 46     | 7 (button, card, dialog, input, textarea, sonner, tooltip) |
| Hooks                                                                   | 4      | 2 (useComposition, usePersistFn)                           |
| Other (App, main, ErrorBoundary, ThemeContext, utils, const, index.css) | 8      | 8                                                          |
| **Total source files**                                                  | **68** | **20**                                                     |

---

## Remaining Work (not done in this pass)

1. **Remove unused dependencies from `package.json`** -- ~30 packages are now dead but were not removed because the root `package.json` is shared across workspace packages.
2. **Add `<StrictMode>`** to `main.tsx` (L2 -- low priority).
3. **Add favicon and theme-color meta** to `index.html` (L3 -- needs design input).
4. **Move `usePersistFn` ref update into an effect** for React 19 concurrent mode safety (L4 -- low priority, widely-used pattern).

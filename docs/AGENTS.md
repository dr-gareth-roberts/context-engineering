# AGENTS.md

This file helps AI coding agents understand how to work with this project.

## Project Overview

- **Language**: TypeScript
- **Project**: Monorepo: TypeScript core library (ce-core, ce-memory, ce-providers, ce-cli) + Python SDK + React web playground
- **Package Manager**: pnpm
- **Test Framework**: Vitest
- **Build Tool**: Vite

## Commands

- **Install**: `pnpm install`
- **Dev**: `pnpm dev`
- **Build**: `pnpm build`
- **Test**: `pnpm test` — runs `tsc --noEmit` (type checking) + `vite build` + esbuild (frontend/server build), NOT a test runner
- **Check**: `pnpm check` — type-check only
- **Package Tests**: `pnpm test:packages` — run Vitest suites
- **Test All**: `pnpm test:all` — type-check + build + Vitest
- **Build Packages**: `pnpm build:packages` — tsc per package
- **Build All**: `pnpm build:all` — build everything
- **Lint**: `pnpm lint`
- **Lint Fix**: `pnpm lint:fix` — auto-fix lint issues
- **Format**: `pnpm format`

## Testing

This project uses **Vitest** for testing.

- Write tests for new features before implementation
- Run tests before committing changes
- Aim for good test coverage on critical paths
- Use `describe` and `it` blocks to organize tests
- Mock external dependencies when appropriate

## React Guidelines (ce-web-client only)

- Use functional components with hooks
- Keep components small and focused
- Use custom hooks to share logic
- Prefer composition over inheritance
- Use TypeScript interfaces for props

## Code Style

- Use strict TypeScript settings
- Define types/interfaces for data structures
- Avoid `any` type - use `unknown` if type is truly unknown
- Use type inference where obvious
- Follow existing patterns in the codebase
- Use meaningful variable and function names
- Add comments for complex logic
- Keep functions focused and small
- Run **ESLint** before committing
- Format code with **Prettier**

## Constraints

- Do not modify files outside the project directory
- Ask before making breaking changes
- Prefer editing existing files over creating new ones
- Do not delete files without confirmation
- Keep dependencies minimal - avoid adding new ones without good reason
- Do not commit sensitive data (API keys, secrets, credentials)

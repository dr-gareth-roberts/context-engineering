# AGENTS.md

This file helps Autohand understand how to work with this project.

## Project Overview

- **Language**: TypeScript
- **Framework**: React
- **Package Manager**: pnpm
- **Test Framework**: Vitest
- **Build Tool**: Vite

## Commands

- **Install**: `pnpm install`
- **Dev**: `pnpm dev`
- **Build**: `pnpm build`
- **Test**: `pnpm test` (root web/tooling smoke test)
- **Package Tests**: `pnpm test:packages`
- **Lint**: `pnpm lint`
- **Format**: `pnpm format`

## Testing

This project uses **Vitest** for testing.

- Write tests for new features before implementation
- Run tests before committing changes
- Aim for good test coverage on critical paths
- Use `describe` and `it` blocks to organize tests
- Mock external dependencies when appropriate

## React Guidelines

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

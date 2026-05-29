# Releasing

Publishing is automated by [`.github/workflows/publish.yml`](../.github/workflows/publish.yml),
which runs on a published GitHub Release. It first runs the full CI gate, then
publishes the Python package to PyPI and the four public TypeScript packages to npm.

## Package names

- **PyPI:** `context-engineering-toolkit` (import remains `import context_engineering`).
  The bare `context-engineering` name on PyPI is owned by an unrelated project.
- **npm:** `@context-engineering/core`, `@context-engineering/providers`,
  `@context-engineering/memory`, `@context-engineering/cli`.

## One-time setup

**PyPI — trusted publishing (OIDC, no token needed).** Because the project is not
yet on PyPI, register a _pending_ publisher before the first release:

PyPI → _Your account_ → _Publishing_ → _Add a pending publisher_:

| Field             | Value                         |
| ----------------- | ----------------------------- |
| PyPI Project Name | `context-engineering-toolkit` |
| Owner             | `dr-gareth-roberts`           |
| Repository name   | `context-engineering`         |
| Workflow name     | `publish.yml`                 |
| Environment       | _(leave blank)_               |

The `pypi` job already requests `id-token: write`, so no API token is required.

**npm.** Own the `@context-engineering` scope (create the org/scope under your npm
account), then add an `NPM_TOKEN` repository secret. Provenance is already enabled
via `publishConfig` on each published package and the job's `id-token: write`.

## Cutting a release

1. Bump versions: `python/pyproject.toml` (`version`) and each published
   `packages/ce-*/package.json` (`version`) as needed.
2. Update [`CHANGELOG.md`](../CHANGELOG.md).
3. Create a GitHub Release with a `vX.Y.Z` tag. `publish.yml` runs the CI gate,
   then publishes to PyPI and npm.
4. Verify: `pip install context-engineering-toolkit` and
   `npm view @context-engineering/core version`.

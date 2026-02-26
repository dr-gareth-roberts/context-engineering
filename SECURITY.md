# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability, please report it responsibly.

**Do not open a public GitHub issue for security vulnerabilities.**

Instead, email **gareth@zmail.com** with:

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

You should receive an acknowledgment within 48 hours. We will work with you to understand the issue and coordinate a fix before any public disclosure.

## Scope

This project processes user-provided context items and token budgets. Relevant security concerns include:

- **Input validation**: Malformed items, extreme values, injection via content fields
- **File operations**: FileStore (JSONL) and SqliteStore write to disk — path traversal, symlink attacks
- **Dependencies**: Supply chain risks from npm/PyPI packages

## Security Practices

- All inputs are validated via Zod (TypeScript) and Pydantic (Python) before processing
- File writes use atomic write-to-tmp + rename to prevent partial writes
- SQLite uses parameterized queries
- Dependencies are kept minimal and version-pinned

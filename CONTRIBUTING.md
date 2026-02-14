# Contributing to Initiative

Thanks for your interest in contributing! This guide covers what you need to know as a developer working on the codebase.

## Getting Set Up

Follow the [Manual Development Setup](./README.md#manual-development-setup) in the README to get the backend and frontend running locally. The [Key Environment Variables](./README.md#key-environment-variables) section covers configuration.

## Running Tests

```bash
# All backend tests
cd backend && pytest

# All frontend tests
cd frontend && pnpm test:run

# Only tests related to files you've changed (vs main)
cd backend && ./scripts/test-changed.sh
cd frontend && ./scripts/test-changed.sh

# Only tests for staged files
cd backend && ./scripts/test-changed.sh --staged
cd frontend && ./scripts/test-changed.sh --staged
```

## Code Style

- **Python**: 4-space indent, full type hints, `snake_case` functions, `PascalCase` models/schemas. Lint with `ruff check app`.
- **TypeScript/React**: `PascalCase` components, `useThing` hooks. Lint with `pnpm lint`.

Both linters must pass before merging.

## Project Layout

- `backend/app/api/` — FastAPI routers
- `backend/app/models/` — SQLModel domain models
- `backend/app/schemas/` — Request/response payloads
- `backend/app/services/` — Business logic
- `frontend/src/pages/` — Route-level React components
- `frontend/src/features/` — Feature-specific components and logic
- `frontend/src/hooks/` — Shared React hooks
- `frontend/src/api/` — API client and query hooks

Tests are co-located next to source files (`_test.py` for backend, `.test.ts` for frontend). Shared test factories live in `backend/app/testing/` and `frontend/src/__tests__/factories/`.

## Submitting Changes

1. Fork the repo and create a branch from `main`
2. Make your changes
3. Ensure tests and linters pass
4. Keep commits focused — separate backend, frontend, and infra changes when practical
5. Open a pull request describing what changed and why
6. Include screenshots or GIFs for UI changes

## Reporting Issues

Use the [issue templates](https://github.com/Morelitea/initiative/issues/new/choose) to file bug reports or feature requests.

## Security Vulnerabilities

Please **do not** open a public issue for security vulnerabilities. See [SECURITY.md](SECURITY.md) for responsible disclosure instructions.

## License

By contributing, you agree to the terms of the [Contributor License Agreement](./CLA.md).

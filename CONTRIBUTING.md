# Contributing to CareerFit AI

Thanks for helping improve CareerFit AI.

## How to Contribute

1. Fork the repository and create a feature branch.
2. Keep changes focused on one bug, feature, or documentation improvement.
3. Run the relevant checks before opening a pull request.
4. Describe what changed, why it changed, and how you tested it.

## Local Checks

Backend:

```bash
cd backend
uv sync
uv run pytest
```

Frontend:

```bash
cd frontend
npm install
npm run build
```

## Project Guidelines

- Prefer small, readable changes over broad rewrites.
- Keep public API changes documented in `README.md`.
- Do not commit secrets, tokens, local database dumps, or private resume data.
- Use clear issue and pull request titles.

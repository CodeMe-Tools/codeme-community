# Contributing to codeme-community

Thank you for contributing to `codeme-community`.

## Development Workflow
1. Ensure your local branch is branched from `main`.
2. All commits must follow Conventional Commits (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`).
3. Every change must pass deterministic verification prior to pull request submission:
   - `codeme-syntax run --repo .`
   - `codeme-quality run --repo .`
   - `codeme-verify run --repo .`
   - `codeme-invariant run --repo .`
4. Code must satisfy the universal contract: exit code `0` and empty stdout/stderr on success.

# Contributing to Claudealytics

Thanks for your interest in contributing! This guide covers everything you need to get started.

## Development Setup

1. **Clone the repo**

   ```bash
   git clone https://github.com/sergei1503/claudealytics.git
   cd claudealytics
   ```

2. **Install dependencies** (requires [uv](https://docs.astral.sh/uv/))

   ```bash
   uv sync --extra dev --extra test
   ```

3. **Run the dashboard**

   ```bash
   uv run claudealytics dashboard
   ```

## Testing

```bash
uv run pytest -v
```

## Linting & Formatting

We use [Ruff](https://docs.astral.sh/ruff/) for linting and formatting:

```bash
uv run ruff check src/ tests/    # Lint
uv run ruff format src/ tests/   # Format
```

Please ensure your code passes both checks before submitting a PR.

## Pull Request Process

1. **Fork** the repository
2. **Create a branch** from `dev` (not `main`):
   ```bash
   git checkout dev
   git checkout -b feat/my-feature
   ```
3. **Make your changes** with clear, focused commits
4. **Run tests and lint** to make sure everything passes
5. **Open a PR** against the `dev` branch

### Commit Messages

We follow [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` — New feature
- `fix:` — Bug fix
- `docs:` — Documentation only
- `refactor:` — Code change that neither fixes a bug nor adds a feature
- `test:` — Adding or updating tests
- `ci:` — CI/CD changes

### PR Guidelines

- Keep PRs focused on a single change
- Include a clear description of what and why
- Add tests for new functionality
- Update documentation if behavior changes

## Branch Strategy

- **`dev`** — Active development. All PRs target this branch.
- **`main`** — Stable releases. Only updated via merges from `dev`.

## Reporting Issues

Use [GitHub Issues](https://github.com/sergei1503/claudealytics/issues) for bugs and feature requests. Please include:

- Steps to reproduce (for bugs)
- Expected vs actual behavior
- Python version and OS

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

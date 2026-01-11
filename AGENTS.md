# Agentic Coding Guidelines for Trello Fetcher

This repository contains a Python-based CLI tool for fetching cards and boards from Trello.

## 🛠 Build, Lint, and Test Commands

This project uses `uv` for dependency management and environment isolation.

### Installation
```bash
# Install dependencies and create a virtual environment
uv sync
```

### Running the CLI
```bash
# Main card fetcher
uv run python -m trello_fetcher --board-id <ID> --format text

# List boards to find IDs
uv run python -m trello_fetcher.list_boards --format text
```

### Linting and Testing
Currently, the project does not have dedicated linting or testing dependencies (like `ruff` or `pytest`). 
- **Type Checking**: Use `mypy` or `pyright` if available in your environment.
- **Testing**: No test suite exists. If you add tests, place them in a `tests/` directory and use `pytest`.

## 🎨 Code Style Guidelines

### Python Version
- Target **Python 3.12+**.
- Always use `from __future__ import annotations` at the top of every file.

### Imports
- Group imports: standard library, third-party, then local modules.
- Use absolute imports for local modules (e.g., `from .fetch_tasks import ...`).

### Type Hinting
- Strict type hinting is required for all function signatures and class members.
- Use `|` for unions (e.g., `str | None`) instead of `Optional`.
- Use built-in generics (e.g., `list[str]`, `dict[str, Any]`).

### Data Models
- Use `@dataclass(frozen=True, slots=True)` for data structures and models.
- Avoid complex classes; prefer functional approaches with plain data objects.

### Naming Conventions
- **Files**: `snake_case.py`.
- **Classes**: `PascalCase`.
- **Functions/Variables**: `snake_case`.
- **Constants**: `UPPER_SNAKE_CASE`.
- **Private members**: Prefix with a single underscore `_`.

### Error Handling
- Use `RuntimeError` for operational errors (e.g., API failures).
- Use `SystemExit` with a descriptive message for CLI-level errors in `main`.
- Avoid broad `except Exception:` blocks; catch specific errors (e.g., `urllib.error.HTTPError`).

### API Interactions
- All Trello API calls must go through the `TrelloClient` class in `fetch_tasks.py`.
- The client uses `urllib.request` to keep dependencies minimal.
- Common patterns:
  - `fetch_cards_for_board(board_id, include_closed=False)`
  - `fetch_lists_for_board(board_id, include_closed=True)`
  - `fetch_my_boards(include_closed=False)`

### Core Data Models
Refer to `fetch_tasks.py` for the source of truth.
- `Task`: Main model for Trello cards.
- `Board`: Model for Trello boards (defined in `list_boards.py`).

Example `Task` usage:
```python
task = Task(
    id="...",
    name="...",
    url="...",
    short_url="...",
    desc="...",
    due="2026-01-11T12:00:00Z",
    due_complete=False,
    closed=False,
    list_id="...",
    list_name="...",
    last_activity="...",
    labels=["label1", "label2"]
)
```

### CLI Implementation
- Use `argparse` for argument parsing.
- Implement a `main(argv: list[str] | None = None) -> int` function.
- Support `.env` files via the internal `_load_env` utility.
- Entry points are defined in `pyproject.toml` (if any) or invoked via `python -m`.

## 📁 Project Structure
- `src/trello_fetcher/`: Core package.
- `src/trello_fetcher/__main__.py`: CLI entry point (calls `fetch_tasks.main`).
- `src/trello_fetcher/fetch_tasks.py`: Primary logic for fetching cards.
- `src/trello_fetcher/list_boards.py`: Utility for listing boards.
- `py.typed`: Marker file for PEP 561 compliance.

## 📝 Example CLI usage for Development
```bash
# Fetch and print as JSON
uv run python -m trello_fetcher --board-id 123

# Fetch and print as Text
uv run python -m trello_fetcher --board-id 123 --format text --include-desc

# Save to file
uv run python -m trello_fetcher --board-id 123 --out cards.json
```

## 🤖 AI Context
- No specific `.cursorrules` or `.github/copilot-instructions.md` exist.
- Always follow the patterns in `fetch_tasks.py` for new feature implementation.
- Maintain the lightweight, "mostly standard library" feel of the project.
- When adding new modules, ensure they are placed inside `src/trello_fetcher/`.
- Ensure all new files include `from __future__ import annotations`.

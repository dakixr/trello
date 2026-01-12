# Agent Guide - Trello Fetcher

This document provides essential information for agentic coding assistants working on the `trello_fetcher` repository.

## Project Overview
A Python-based utility to fetch cards from Trello boards and lists. It includes both a CLI for data extraction and a TUI (Textual-based) for interactive browsing.

- **Stack:** Python 3.12+, `uv`, `requests`, `textual`.
- **Layout:** Source code is in `src/trello_fetcher/`.
- **Key Modules:**
    - `fetch_tasks.py`: Core logic for Trello API interaction and Task models.
    - `list_boards.py`: Logic for listing and modeling Trello boards.
    - `tui.py`: Textual-based user interface implementation.
    - `__main__.py`: CLI entry point for the package.

## Critical Commands

### Environment Setup
```bash
# Install dependencies and create venv
uv sync

# Copy example env
cp env.example .env
```

### Running the Application
```bash
# Start the TUI (main entry point)
uv run trello

# Run CLI to fetch tasks
uv run python -m trello_fetcher.fetch_tasks --board-id <ID> --format text

# List boards to find IDs
uv run python -m trello_fetcher.list_boards
```

### Development & Quality
*Note: This project currently has no configured tests or linters in pyproject.toml. However, `.ruff_cache` exists, suggesting ruff usage.*

```bash
# Linting (Recommended: ruff)
uv run ruff check .
uv run ruff format .

# Testing (Recommended: pytest)
uv run pytest
uv run pytest tests/test_file.py::test_function
```

## Code Style Guidelines

### 1. Python Standards
- Use **Python 3.12+** features (e.g., `type1 | type2` union syntax).
- **Type Hints:** Mandatory for all function signatures and public attributes.
- **Imports:** 
    - Always include `from __future__ import annotations`.
    - Group imports: Standard library, third-party, local modules.
    - Sort imports alphabetically within groups.
- **Formatting:** Follow PEP 8. Use 4 spaces for indentation.

### 2. Architecture & Patterns
- **Data Models:** Use `dataclass(frozen=True, slots=True)` for immutable data structures (see `Task` in `fetch_tasks.py` and `Board` in `list_boards.py`).
- **File I/O:** Use `pathlib.Path` instead of `os.path`.
- **Networking:** 
    - `TrelloClient` in `fetch_tasks.py` uses `urllib.request` for base API calls to minimize dependencies.
    - Always handle `urllib.error.HTTPError` and wrap in `RuntimeError` with descriptive messages.
- **TUI (Textual):**
    - Follow the `Screen` and `App` patterns.
    - Use `@work(thread=True)` for all I/O bound tasks (API calls) to keep the UI responsive.
    - Use `self.app.call_from_thread()` to update the UI from worker threads.
    - Define CSS as a class attribute `CSS` within `Screen` or `App` classes.

### 3. Error Handling
- Use descriptive exceptions. `RuntimeError` is preferred for API or business logic failures.
- In CLI entry points, use `raise SystemExit("message")` for user-facing fatal errors to ensure clean exits with non-zero codes.
- In TUI, catch exceptions in workers and use `self.app.notify()` for transient errors or update UI labels for persistent errors.

### 4. Naming Conventions
- Variables/Functions: `snake_case`.
- Classes: `PascalCase`.
- Private members: `_leading_underscore`.
- Constants: `UPPER_SNAKE_CASE`.

## Trello API Integration
The application interacts with the Trello REST API v1.
- Base URL: `https://api.trello.com/1`
- Authentication: Requires `api_key` and `token` passed as query parameters.
- Common Fields fetched: `id, name, desc, due, dueComplete, url, shortUrl, labels, idList, closed, dateLastActivity`.
- Reference: [Trello API Documentation](https://developer.atlassian.com/cloud/trello/rest/)

## TUI Structure
The TUI (`tui.py`) uses a screen-based navigation:
1. `BoardSelectScreen`: Lists available boards for the user to choose from.
2. `TaskViewerScreen`: Displays tasks for the selected board, organized by list. Includes a detail panel with Markdown support for descriptions.

## Development Workflow for Agents
1. **Analyze Requirements:** Determine if the change affects data models, API fetching, CLI, or TUI.
2. **Update Models:** If adding fields, update the relevant `@dataclass` in `fetch_tasks.py` or `list_boards.py`.
3. **API Logic:** Update `TrelloClient` methods to fetch the necessary data. Ensure proper type casting from JSON responses.
4. **CLI Support:** Update `_write_output` and `main()` in `fetch_tasks.py` if new flags or output formats are needed.
5. **TUI Support:**
    - Update `compose()` to add new widgets.
    - Update CSS in the `CSS` class attribute.
    - Update `@work` methods for background data fetching.
    - Use `self.app.notify()` for user feedback on actions.
6. **Verification:**
    - Run `uv run ruff check .` to ensure no linting regressions.
    - Run the CLI with various flags to verify data extraction.
    - Run the TUI and navigate through screens to ensure UI stability and responsiveness.
    - Add unit tests in `tests/` for complex logic.

## Agent Instructions & Constraints
- **Proactiveness:** 
    - If adding a new data field to `Task`, ensure it's handled in `_cards_to_tasks` and displayed in both CLI output and TUI detail panel.
    - If adding a new CLI flag, consider if it should also be a setting or toggle in the TUI.
- **Documentation:** Maintain Google-style docstrings. Every new class and public method must have a docstring.
- **Security:** 
    - NEVER commit `.env` files or hardcode API keys.
    - Use `_load_env` to load credentials from `.env` during local development.
- **Testing:** If you implement a new feature, you are encouraged to add a corresponding test in a `tests/` directory using `pytest`.
- **TUI Responsiveness:** Always ensure API calls are offloaded to threads using Textual's `@work` decorator.
- **Dependency Management:** Use `uv add <package>` to add new dependencies and ensure `pyproject.toml` is updated.

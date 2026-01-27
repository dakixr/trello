#!/usr/bin/env python3
"""`python -m trello_fetcher` entry point.

The canonical CLI is exposed as the `trello` script (see `pyproject.toml`).
This module delegates to the same implementation for parity.
"""

from __future__ import annotations

from .main import main

if __name__ == "__main__":
    raise SystemExit(main())

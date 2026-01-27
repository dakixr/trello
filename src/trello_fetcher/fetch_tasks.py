#!/usr/bin/env python3
"""Trello Fetcher - Enhanced CLI with board management and improved output."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

TRELLO_BASE_URL = "https://api.trello.com/1"
CONFIG_DIR = Path.home() / ".config" / "trello_fetcher"
BOARDS_CONFIG_FILE = CONFIG_DIR / "boards.json"
DONE_TASKS_FILE = CONFIG_DIR / "done_tasks.json"


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _parse_trello_datetime(value: str | None) -> str | None:
    """
    Trello datetimes are usually ISO-8601 strings like '2026-01-11T12:34:56.789Z'.
    We normalize them to an ISO string with timezone offset when possible.
    """
    if not value:
        return None
    try:
        # fromisoformat doesn't accept a trailing "Z"
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.isoformat()
    except ValueError:
        # If Trello returns an unexpected format, keep as original string.
        return value


@dataclass(frozen=True, slots=True)
class BoardConfig:
    """Configuration for a linked board."""

    board_id: str
    repo_path: str | None = None
    created_at: str | None = None
    last_synced: str | None = None


class TrelloClient:
    def __init__(self, *, api_key: str, token: str, timeout_s: float = 20.0) -> None:
        self._api_key = api_key
        self._token = token
        self._timeout_s = timeout_s

    def close(self) -> None:
        return None

    def _get(self, path: str, *, params: dict[str, Any]) -> Any:
        merged = {
            "key": self._api_key,
            "token": self._token,
            **params,
        }
        qs = urlencode({k: str(v) for k, v in merged.items() if v is not None})
        url = f"{TRELLO_BASE_URL}{path}?{qs}"
        req = Request(url, headers={"Accept": "application/json"})

        try:
            with urlopen(req, timeout=self._timeout_s) as resp:
                raw = resp.read().decode("utf-8")
        except HTTPError as e:
            try:
                detail = e.read().decode("utf-8")
            except Exception:
                detail = str(e)
            raise RuntimeError(f"Trello API error {e.code}: {detail}") from e

        return json.loads(raw)

    def _post(self, path: str, *, params: dict[str, Any]) -> Any:
        """Make a POST request to Trello API."""
        merged = {
            "key": self._api_key,
            "token": self._token,
            **params,
        }
        qs = urlencode({k: str(v) for k, v in merged.items() if v is not None})
        url = f"{TRELLO_BASE_URL}{path}?{qs}"
        req = Request(url, method="POST", headers={"Accept": "application/json"})

        try:
            with urlopen(req, timeout=self._timeout_s) as resp:
                raw = resp.read().decode("utf-8")
        except HTTPError as e:
            try:
                detail = e.read().decode("utf-8")
            except Exception:
                detail = str(e)
            raise RuntimeError(f"Trello API error {e.code}: {detail}") from e

        return json.loads(raw) if raw else None

    def fetch_cards_for_list(
        self, list_id: str, *, include_closed: bool
    ) -> list[dict[str, Any]]:
        return self._get(
            f"/lists/{list_id}/cards",
            params={
                "filter": "all" if include_closed else "open",
                "fields": "id,name,desc,due,dueComplete,url,shortUrl,labels,idList,closed,dateLastActivity",
            },
        )

    def fetch_cards_for_board(
        self, board_id: str, *, include_closed: bool
    ) -> list[dict[str, Any]]:
        return self._get(
            f"/boards/{board_id}/cards",
            params={
                "filter": "all" if include_closed else "open",
                "fields": "id,name,desc,due,dueComplete,url,shortUrl,labels,idList,closed,dateLastActivity",
            },
        )

    def fetch_lists_for_board(
        self, board_id: str, *, include_closed: bool
    ) -> list[dict[str, Any]]:
        return self._get(
            f"/boards/{board_id}/lists",
            params={
                "filter": "all" if include_closed else "open",
                "fields": "id,name,closed",
            },
        )

    def fetch_list(self, list_id: str) -> dict[str, Any]:
        return self._get(
            f"/lists/{list_id}",
            params={
                "fields": "id,name,closed",
            },
        )

    def fetch_my_boards(self, *, include_closed: bool) -> list[dict[str, Any]]:
        return self._get(
            "/members/me/boards",
            params={
                "filter": "all" if include_closed else "open",
                "fields": "id,name,url,shortUrl,closed,dateLastActivity",
            },
        )

    def fetch_board(self, board_id: str) -> dict[str, Any]:
        """Fetch a single board by ID.

        Args:
            board_id: Trello board ID.

        Returns:
            Board dict containing at least id, name, url, shortUrl, closed.
        """
        return self._get(
            f"/boards/{board_id}",
            params={
                "fields": "id,name,url,shortUrl,closed,dateLastActivity",
            },
        )

    def fetch_card(self, card_id: str) -> dict[str, Any]:
        """Fetch a single card by ID.

        Args:
            card_id: Trello card ID.

        Returns:
            Card dict containing at least id, name, idBoard.
        """
        return self._get(
            f"/cards/{card_id}",
            params={
                "fields": "id,name,idBoard",
            },
        )

    def add_comment_to_card(self, card_id: str, text: str) -> dict[str, Any]:
        """Add a comment to a Trello card.

        Args:
            card_id: The ID of the card to add a comment to.
            text: The comment text.

        Returns:
            The created comment action as a dictionary.
        """
        return self._post(
            f"/cards/{card_id}/actions/comments",
            params={"text": text},
        )


@dataclass(frozen=True, slots=True)
class Task:
    id: str
    name: str
    url: str | None
    short_url: str | None
    desc: str | None
    due: str | None
    due_complete: bool | None
    closed: bool | None
    list_id: str | None
    list_name: str | None
    last_activity: str | None
    labels: list[str]
    board_config: BoardConfig | None = None


def _load_env_from_path(path: Path) -> None:
    """
    Load environment variables from a single .env file.

    - Supports lines like KEY=VALUE (VALUE may be quoted).
    - Ignores blank lines and comments (# ...).
    - Does not override existing environment variables.
    """
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and ((value[0] == value[-1]) and value[0] in {"'", '"'}):
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def _load_board_configs() -> dict[str, BoardConfig]:
    """Load board configurations from disk."""
    if not BOARDS_CONFIG_FILE.exists():
        return {}

    try:
        data = json.loads(BOARDS_CONFIG_FILE.read_text())
        configs: dict[str, BoardConfig] = {}
        for board_id, config_data in data.items():
            configs[board_id] = BoardConfig(
                board_id=board_id,
                repo_path=config_data.get("repo_path"),
                created_at=config_data.get("created_at"),
                last_synced=config_data.get("last_synced"),
            )
        return configs
    except (json.JSONDecodeError, OSError):
        return {}


def _save_board_configs(configs: dict[str, BoardConfig]) -> None:
    """Persist all board configs to disk."""
    BOARDS_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {
        bid: {
            "repo_path": cfg.repo_path,
            "created_at": cfg.created_at,
            "last_synced": cfg.last_synced,
        }
        for bid, cfg in configs.items()
    }
    BOARDS_CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _save_board_config(board_id: str, repo_path: str | None) -> None:
    """Save a board configuration to disk."""
    # Load existing data for other boards
    configs = _load_board_configs()
    if repo_path:
        existing = configs.get(board_id)
        configs[board_id] = BoardConfig(
            board_id=board_id,
            repo_path=repo_path,
            created_at=(existing.created_at if existing else _now_iso()),
            last_synced=(existing.last_synced if existing else None),
        )
    elif board_id in configs:
        del configs[board_id]

    _save_board_configs(configs)


def _touch_board_last_synced(board_id: str, last_synced: str) -> None:
    """Update `last_synced` for an existing linked board."""
    configs = _load_board_configs()
    existing = configs.get(board_id)
    if existing is None:
        return
    configs[board_id] = BoardConfig(
        board_id=existing.board_id,
        repo_path=existing.repo_path,
        created_at=existing.created_at,
        last_synced=last_synced,
    )
    _save_board_configs(configs)


def _load_done_tasks(board_id: str) -> set[str]:
    """Load done task IDs for a board from disk."""
    if not DONE_TASKS_FILE.exists():
        return set()

    try:
        data = json.loads(DONE_TASKS_FILE.read_text())
        return set(data.get(board_id, []))
    except (json.JSONDecodeError, OSError):
        return set()


def _save_done_tasks(board_id: str, done_task_ids: set[str]) -> None:
    """Save done task IDs for a board to disk."""
    DONE_TASKS_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Load existing data for other boards
    try:
        if DONE_TASKS_FILE.exists():
            data = json.loads(DONE_TASKS_FILE.read_text())
        else:
            data = {}
    except (json.JSONDecodeError, OSError):
        data = {}
    data[board_id] = sorted(done_task_ids)
    DONE_TASKS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _cards_to_tasks(
    cards: list[dict[str, Any]], *, list_id_to_name: dict[str, str]
) -> list[Task]:
    tasks: list[Task] = []
    for card in cards:
        labels = card.get("labels") or []
        label_names = [
            str(label.get("name") or "").strip()
            for label in labels
            if isinstance(label, dict)
        ]
        label_names = [n for n in label_names if n]

        list_id = card.get("idList")
        list_name = None
        if isinstance(list_id, str):
            list_name = list_id_to_name.get(list_id)

        tasks.append(
            Task(
                id=str(card.get("id", "")),
                name=str(card.get("name", "")),
                url=card.get("url"),
                short_url=card.get("shortUrl"),
                desc=card.get("desc"),
                due=_parse_trello_datetime(card.get("due")),
                due_complete=card.get("dueComplete"),
                closed=card.get("closed"),
                list_id=list_id if isinstance(list_id, str) else None,
                list_name=list_name,
                last_activity=_parse_trello_datetime(card.get("dateLastActivity")),
                labels=label_names,
                board_config=None,
            )
        )
    return tasks


def _write_output(
    tasks: list[Task],
    *,
    fmt: Literal["json", "text"],
    out_path: Path | None,
    include_desc: bool,
) -> None:
    if fmt == "text":
        lines: list[str] = []
        for t in tasks:
            # Use board name if list_name not available
            bucket = t.list_name or t.list_id or "unknown"
            lines.append(f"[{bucket}] {t.name}")
            # Add board path after bucket if available
            if t.board_config and t.board_config.repo_path:
                lines.append(f"  → {t.board_config.repo_path}")
            if include_desc and t.desc:
                lines.append((t.desc or "").strip())
        content = "\n".join(lines) + ("\n" if lines else "")
    else:
        content = json.dumps([asdict(t) for t in tasks], indent=2) + "\n"

    if out_path:
        out_path.write_text(content, encoding="utf-8")
    else:
        print(content, end="")


def _load_env(env_file: str | None) -> None:
    """
    Load environment variables from .env files.

    Search order:
    1. Explicit env_file if provided.
    2. .env in current working directory.
    3. ~/.config/trello_fetcher/.env as a global fallback.

    Variables from earlier sources take precedence (won't be overridden).
    """
    if env_file:
        _load_env_from_path(Path(env_file))
    else:
        # Load from cwd first
        _load_env_from_path(Path.cwd() / ".env")
        # Then load from global config dir (won't override existing vars)
        _load_env_from_path(Path.home() / ".config" / "trello_fetcher" / ".env")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Trello CLI: Fetch, manage boards, enhanced output", prog="trello"
    )

    parser.add_argument(
        "--env-file", help="Path to a .env file (defaults to ./.env when present)."
    )

    parser.add_argument(
        "--api-key", default=None, help="Trello API key (or set TRELLO_API_KEY)."
    )

    parser.add_argument(
        "--token", default=None, help="Trello token (or set TRELLO_TOKEN)."
    )

    parser.add_argument(
        "--list-id",
        default=None,
        help="Fetch cards from this list (or set TRELLO_LIST_ID).",
    )

    parser.add_argument(
        "--board-id",
        default=None,
        help="Fetch cards from this board (or set TRELLO_BOARD_ID).",
    )

    parser.add_argument(
        "--include-closed",
        action="store_true",
        help="Include archived/closed cards (default: only open cards).",
    )

    parser.add_argument("--format", choices=("json", "text"), default="json")
    parser.add_argument(
        "--include-desc",
        action="store_true",
        help="Include card descriptions in text output (default: omit).",
    )

    parser.add_argument(
        "--out", default=None, help="Write output to a file instead of stdout."
    )

    # Board management subcommands
    subparsers = parser.add_subparsers(dest="command", help="Board management commands")

    link_parser = subparsers.add_parser(
        "link-board", help="Link a Trello board to a local path"
    )
    link_parser.add_argument("board-id", help="Trello board ID")
    link_parser.add_argument(
        "--path", required=True, help="Local path to link (e.g., ~/Projects/ionisium)"
    )

    unlink_parser = subparsers.add_parser(
        "unlink-board", help="Unlink a Trello board from a local path"
    )
    unlink_parser.add_argument("board-id", help="Trello board ID")

    subparsers.add_parser(
        "show-boards", help="Show all linked boards with their local paths"
    )

    args = parser.parse_args(argv)

    _load_env(args.env_file)

    api_key: str | None = (
        args.api_key if isinstance(args.api_key, str) else None
    ) or os.getenv("TRELLO_API_KEY")
    token: str | None = (
        args.token if isinstance(args.token, str) else None
    ) or os.getenv("TRELLO_TOKEN")

    if not api_key or not token:
        # Only require credentials for fetch operations, not for board management (unless needed later)
        if args.command not in ("link-board", "unlink-board", "show-boards"):
            raise SystemExit(
                "Missing Trello credentials. Set TRELLO_API_KEY and TRELLO_TOKEN (or pass --api-key/--token)."
            )

    if args.command == "link-board":
        board_id = args.link_board.board_id
        repo_path = args.link_board.path
        _save_board_config(board_id, repo_path)
        print(f"✓ Linked board {board_id} → {repo_path}")
    elif args.command == "unlink-board":
        board_id = args.unlink_board.board_id
        _save_board_config(board_id, repo_path=None)
        print(f"✓ Unlinked board {board_id}")
    elif args.command == "show-boards":
        configs = _load_board_configs()
        if configs:
            print("Linked boards:")
            for board_id, cfg in configs.items():
                repo = cfg.repo_path or "No path"
                last_synced = cfg.last_synced or "Never"
                print(f"  {board_id} → {repo} (last synced: {last_synced})")
        else:
            print("No boards linked.")
    # Existing fetch logic for cards/boards
    if (args.list_id is None) == (args.board_id is None) and args.command is None:
        raise SystemExit(
            "Provide exactly one of --list-id or --board-id (or set TRELLO_LIST_ID/TRELLO_BOARD_ID)."
        )

    # Initialize tasks list
    tasks: list[Task] = []

    if args.command is None:
        if not api_key or not token:
            # Keep this explicit so type checkers can narrow to `str`.
            raise SystemExit(
                "Missing Trello credentials. Set TRELLO_API_KEY and TRELLO_TOKEN (or pass --api-key/--token)."
            )

        out_path = Path(args.out).expanduser() if args.out else None

        client = TrelloClient(api_key=api_key, token=token)
        try:
            list_id_to_name: dict[str, str] = {}

            # Load board configs to get repo paths for output
            configs = _load_board_configs()

            # Determine mode: single board or all boards
            if args.board_id is not None:
                # Single board mode: Fetch from specified board with repo path from config
                cards = client.fetch_cards_for_board(
                    args.board_id, include_closed=args.include_closed
                )

                # Fetch lists for list name resolution
                lists = client.fetch_lists_for_board(
                    args.board_id, include_closed=args.include_closed
                )
                for lst in lists:
                    if isinstance(lst, dict):
                        lst_id = lst.get("id")
                        lst_name = lst.get("name")
                        if isinstance(lst_id, str) and isinstance(lst_name, str):
                            list_id_to_name[lst_id] = lst_name

                tasks.extend(_cards_to_tasks(cards, list_id_to_name=list_id_to_name))

            elif args.list_id is not None:
                # Fetch from single list
                cards = client.fetch_cards_for_list(
                    args.list_id, include_closed=args.include_closed
                )
                # We can try to fetch the list details to get the name
                try:
                    lst = client.fetch_list(args.list_id)
                    if isinstance(lst, dict):
                        list_id_to_name[args.list_id] = str(lst.get("name", ""))
                except Exception:
                    pass
                tasks.extend(_cards_to_tasks(cards, list_id_to_name=list_id_to_name))

        except RuntimeError as e:
            # Best-effort: still return cards even if list lookup fails.
            print(f"Error fetching data: {e}")
            pass
        finally:
            client.close()

        # Filter out completed tasks by default (closed or due complete)
        if not args.include_closed:
            tasks = [t for t in tasks if not t.closed and not t.due_complete]

        _write_output(
            tasks,
            fmt=args.format,
            out_path=out_path,
            include_desc=bool(args.include_desc),
        )
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

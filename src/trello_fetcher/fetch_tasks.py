from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

TRELLO_BASE_URL = "https://api.trello.com/1"


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
        # If Trello returns an unexpected format, keep the original string.
        return value


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
        """Make a POST request to the Trello API."""
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
            bucket = t.list_name or t.list_id or "unknown"
            lines.append(f"[{bucket}] {t.name}")
            if include_desc:
                lines.append((t.desc or "").strip())
        content = "\n".join(lines) + ("\n" if lines else "")
    else:
        content = json.dumps([asdict(t) for t in tasks], indent=2) + "\n"

    if out_path:
        out_path.write_text(content, encoding="utf-8")
    else:
        print(content, end="")


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


def _load_env(env_file: str | None) -> None:
    """
    Load environment variables from .env files.

    Search order:
    1. Explicit env_file if provided.
    2. .env in the current working directory.
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
    parser = argparse.ArgumentParser(description="Fetch tasks (cards) from Trello.")
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
    args = parser.parse_args(argv)

    _load_env(args.env_file)

    # argparse stores values as `Any` on Namespace attributes; normalize to `str | None`
    api_key: str | None = (
        args.api_key if isinstance(args.api_key, str) else None
    ) or os.getenv("TRELLO_API_KEY")
    token: str | None = (
        args.token if isinstance(args.token, str) else None
    ) or os.getenv("TRELLO_TOKEN")
    list_id: str | None = (
        args.list_id if isinstance(args.list_id, str) else None
    ) or os.getenv("TRELLO_LIST_ID")
    board_id: str | None = (
        args.board_id if isinstance(args.board_id, str) else None
    ) or os.getenv("TRELLO_BOARD_ID")

    if not api_key or not token:
        raise SystemExit(
            "Missing Trello credentials. Set TRELLO_API_KEY and TRELLO_TOKEN (or pass --api-key/--token)."
        )

    if (list_id is None) == (board_id is None):
        raise SystemExit(
            "Provide exactly one of --list-id or --board-id (or set TRELLO_LIST_ID/TRELLO_BOARD_ID)."
        )

    out_path = Path(args.out).expanduser() if args.out else None

    client = TrelloClient(api_key=api_key, token=token)
    try:
        list_id_to_name: dict[str, str] = {}
        if list_id is not None:
            cards = client.fetch_cards_for_list(
                list_id, include_closed=args.include_closed
            )
            try:
                lst = client.fetch_list(list_id)
                if isinstance(lst, dict):
                    lst_id = lst.get("id")
                    lst_name = lst.get("name")
                    if isinstance(lst_id, str) and isinstance(lst_name, str):
                        list_id_to_name[lst_id] = lst_name
            except RuntimeError:
                # Best-effort: still return cards even if list lookup fails.
                pass
        else:
            # The XOR check above guarantees this
            assert board_id is not None
            try:
                lists = client.fetch_lists_for_board(board_id, include_closed=True)
                if isinstance(lists, list):
                    for lst in lists:
                        if not isinstance(lst, dict):
                            continue
                        lst_id = lst.get("id")
                        lst_name = lst.get("name")
                        if isinstance(lst_id, str) and isinstance(lst_name, str):
                            list_id_to_name[lst_id] = lst_name
            except RuntimeError:
                # Best-effort: still return cards even if list lookup fails.
                pass
            cards = client.fetch_cards_for_board(
                board_id, include_closed=args.include_closed
            )
    finally:
        client.close()

    tasks = _cards_to_tasks(cards, list_id_to_name=list_id_to_name)
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


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from .fetch_tasks import TrelloClient, _load_env


@dataclass(frozen=True, slots=True)
class Board:
    id: str
    name: str
    url: str | None
    short_url: str | None
    closed: bool | None


def _boards_to_models(boards: list[dict[str, object]]) -> list[Board]:
    out: list[Board] = []
    for b in boards:
        if not isinstance(b, dict):
            continue
        url_val = b.get("url")
        short_url_val = b.get("shortUrl")
        closed_val = b.get("closed")
        out.append(
            Board(
                id=str(b.get("id", "")),
                name=str(b.get("name", "")),
                url=url_val if isinstance(url_val, str) else None,
                short_url=short_url_val if isinstance(short_url_val, str) else None,
                closed=closed_val if isinstance(closed_val, bool) else None,
            )
        )
    return out


def _write_output(
    boards: list[Board], *, fmt: Literal["json", "text"], out_path: Path | None
) -> None:
    if fmt == "text":
        lines: list[str] = []
        for b in boards:
            status = " (closed)" if b.closed else ""
            url = b.short_url or b.url or ""
            url_part = f" - {url}" if url else ""
            lines.append(f"- {b.name}{status} (id={b.id}){url_part}")
        content = "\n".join(lines) + ("\n" if lines else "")
    else:
        content = json.dumps([asdict(b) for b in boards], indent=2) + "\n"

    if out_path:
        out_path.write_text(content, encoding="utf-8")
    else:
        print(content, end="")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="List boards for the current Trello user."
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
        "--include-closed",
        action="store_true",
        help="Include closed boards (default: only open boards).",
    )
    parser.add_argument("--format", choices=("json", "text"), default="text")
    parser.add_argument(
        "--out", default=None, help="Write output to a file instead of stdout."
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
        raise SystemExit(
            "Missing Trello credentials. Set TRELLO_API_KEY and TRELLO_TOKEN (or pass --api-key/--token)."
        )

    out_path = Path(args.out).expanduser() if args.out else None

    client = TrelloClient(api_key=api_key, token=token)
    try:
        boards_raw = client.fetch_my_boards(include_closed=bool(args.include_closed))
    finally:
        client.close()

    boards = _boards_to_models(boards_raw if isinstance(boards_raw, list) else [])
    _write_output(boards, fmt=args.format, out_path=out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

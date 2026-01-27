#!/usr/bin/env python3
"""Trello Fetcher CLI entry point.

This module implements the `trello` command (see `pyproject.toml` scripts) using a
subcommand-based CLI:

- `trello boards ...`
- `trello tasks ...`
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, NoReturn

import typer

from .fetch_tasks import (
    TrelloClient,
    _cards_to_tasks,
    _load_board_configs,
    _load_done_tasks,
    _load_env,
    _save_board_config,
    _save_done_tasks,
    _touch_board_last_synced,
)


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _resolve_out_path(value: str | None) -> Path | None:
    return Path(value).expanduser() if value else None


def _write(content: str, *, out_path: Path | None) -> None:
    if out_path is None:
        print(content, end="")
    else:
        out_path.write_text(content, encoding="utf-8")


class OutputFormat(str, Enum):
    """Supported output formats for CLI commands."""

    json = "json"
    text = "text"


def _die(message: str, *, code: int = 1) -> NoReturn:
    """Print a user-facing error message and exit."""

    typer.echo(message, err=True)
    raise typer.Exit(code=code)


def _require_credentials(*, api_key: str | None, token: str | None) -> tuple[str, str]:
    resolved_api_key = api_key or os.getenv("TRELLO_API_KEY")
    resolved_token = token or os.getenv("TRELLO_TOKEN")

    if not resolved_api_key or not resolved_token:
        _die(
            "Missing Trello credentials. Set TRELLO_API_KEY and TRELLO_TOKEN (or pass --api-key/--token)."
        )
    return resolved_api_key, resolved_token


def _boards_list(
    *,
    api_key: str | None,
    token: str | None,
    include_closed: bool,
    fmt: OutputFormat,
    out: str | None,
) -> None:
    resolved_api_key, resolved_token = _require_credentials(
        api_key=api_key, token=token
    )
    out_path = _resolve_out_path(out)

    configs = _load_board_configs()

    client = TrelloClient(api_key=resolved_api_key, token=resolved_token)
    try:
        boards = client.fetch_my_boards(include_closed=include_closed)
    finally:
        client.close()

    board_rows: list[dict[str, Any]] = []
    if isinstance(boards, list):
        for b in boards:
            if not isinstance(b, dict):
                continue
            board_id = str(b.get("id", ""))
            cfg = configs.get(board_id)
            board_rows.append(
                {
                    "id": board_id,
                    "name": str(b.get("name", "")),
                    "url": b.get("url"),
                    "shortUrl": b.get("shortUrl"),
                    "closed": b.get("closed"),
                    "linked_path": cfg.repo_path if cfg else None,
                    "last_synced": cfg.last_synced if cfg else None,
                }
            )

    if fmt == OutputFormat.json:
        _write(json.dumps(board_rows, indent=2) + "\n", out_path=out_path)
        return None

    lines: list[str] = []
    for row in board_rows:
        status = " (closed)" if row.get("closed") else ""
        url = row.get("shortUrl") or row.get("url") or ""
        url_part = f" - {url}" if url else ""
        linked = row.get("linked_path")
        linked_part = f" → {linked}" if linked else ""
        synced = row.get("last_synced")
        synced_part = f" (last synced: {synced})" if synced else ""
        lines.append(
            f"- {row.get('name', '')}{status} (id={row.get('id', '')}){url_part}{linked_part}{synced_part}"
        )
    _write(("\n".join(lines) + ("\n" if lines else "")), out_path=out_path)
    return None


def _boards_link(
    *,
    api_key: str | None,
    token: str | None,
    board_id: str,
    path: str | None,
) -> None:
    resolved_api_key, resolved_token = _require_credentials(
        api_key=api_key, token=token
    )
    repo_path = str(Path(path).expanduser()) if path else str(Path.cwd())

    client = TrelloClient(api_key=resolved_api_key, token=resolved_token)
    try:
        board = client.fetch_board(board_id)
    finally:
        client.close()

    board_name = (
        str(board.get("name", board_id)) if isinstance(board, dict) else board_id
    )
    _save_board_config(board_id, repo_path)
    print(f"✓ Linked board {board_name} ({board_id}) → {repo_path}")
    return None


def _boards_unlink(*, board_id: str) -> None:
    _save_board_config(board_id, repo_path=None)
    print(f"✓ Unlinked board {board_id}")
    return None


def _boards_show(
    *,
    api_key: str | None,
    token: str | None,
    fmt: OutputFormat,
    out: str | None,
) -> None:
    configs = _load_board_configs()
    out_path = _resolve_out_path(out)

    if not configs:
        _write("No boards linked.\n", out_path=out_path)
        return None

    resolved_api_key, resolved_token = _require_credentials(
        api_key=api_key, token=token
    )
    client = TrelloClient(api_key=resolved_api_key, token=resolved_token)
    try:
        rows: list[dict[str, Any]] = []
        for board_id, cfg in configs.items():
            name = board_id
            try:
                b = client.fetch_board(board_id)
                if isinstance(b, dict) and isinstance(b.get("name"), str):
                    name = b["name"]
            except Exception:
                # Best-effort: keep the ID if lookup fails.
                name = board_id
            rows.append(
                {
                    "id": board_id,
                    "name": name,
                    "repo_path": cfg.repo_path,
                    "created_at": cfg.created_at,
                    "last_synced": cfg.last_synced,
                }
            )
    finally:
        client.close()

    if fmt == OutputFormat.json:
        _write(json.dumps(rows, indent=2) + "\n", out_path=out_path)
        return None

    lines: list[str] = ["Linked boards:"]
    for row in rows:
        repo = row.get("repo_path") or "No path"
        last_synced = row.get("last_synced") or "Never"
        lines.append(
            f"- {row.get('name')} (id={row.get('id')}) → {repo} (last synced: {last_synced})"
        )
    _write("\n".join(lines) + "\n", out_path=out_path)
    return None


def _tasks_fetch(
    *,
    api_key: str | None,
    token: str | None,
    board_id: str | None,
    include_closed: bool,
    include_done: bool,
    include_desc: bool,
    fmt: OutputFormat | None,
    out: str | None,
    default_format: OutputFormat,
) -> None:
    resolved_api_key, resolved_token = _require_credentials(
        api_key=api_key, token=token
    )
    out_path = _resolve_out_path(out)
    resolved_fmt = fmt or default_format

    configs = _load_board_configs()
    if board_id:
        board_ids = [str(board_id)]
    else:
        board_ids = list(configs.keys())

    if not board_ids:
        _die(
            "No boards linked. Use 'trello boards list' to see available boards, then 'trello boards link <id>' to link one."
        )

    client = TrelloClient(api_key=resolved_api_key, token=resolved_token)
    try:
        json_rows: list[dict[str, Any]] = []
        text_lines: list[str] = []

        for board_id in board_ids:
            board_cfg = configs.get(board_id)
            board = client.fetch_board(board_id)
            board_name = (
                str(board.get("name", board_id))
                if isinstance(board, dict)
                else board_id
            )

            lists_raw = client.fetch_lists_for_board(
                board_id, include_closed=include_closed
            )
            list_id_to_name: dict[str, str] = {}
            if isinstance(lists_raw, list):
                for lst in lists_raw:
                    if not isinstance(lst, dict):
                        continue
                    lst_id = lst.get("id")
                    lst_name = lst.get("name")
                    if isinstance(lst_id, str) and isinstance(lst_name, str):
                        list_id_to_name[lst_id] = lst_name

            cards = client.fetch_cards_for_board(
                board_id, include_closed=include_closed
            )
            tasks = _cards_to_tasks(
                cards if isinstance(cards, list) else [],
                list_id_to_name=list_id_to_name,
            )

            # Filter closed/due-complete by default unless explicitly included.
            if not include_closed:
                tasks = [t for t in tasks if not t.closed and not t.due_complete]

            done_ids = _load_done_tasks(board_id)
            if not include_done:
                tasks = [t for t in tasks if t.id not in done_ids]

            # Update last-synced timestamp for linked boards.
            if board_cfg is not None:
                _touch_board_last_synced(board_id, _now_iso())

            if resolved_fmt == OutputFormat.json:
                repo_path = board_cfg.repo_path if board_cfg else None
                for t in tasks:
                    row = asdict(t)
                    row.update(
                        {
                            "board_id": board_id,
                            "board_name": board_name,
                            "repo_path": repo_path,
                            "done": t.id in done_ids,
                        }
                    )
                    json_rows.append(row)
                continue

            # Text output: group by list/bucket.
            repo_path = board_cfg.repo_path if board_cfg else None
            text_lines.append(f"[{board_name}]")
            if repo_path:
                text_lines.append(f"  → {repo_path}")

            by_bucket: dict[str, list[Any]] = defaultdict(list)
            for t in tasks:
                bucket = t.list_name or t.list_id or "unknown"
                by_bucket[bucket].append(t)

            for bucket in sorted(by_bucket.keys()):
                text_lines.append(f"  [{bucket}]")
                for t in by_bucket[bucket]:
                    done_marker = "✓" if t.id in done_ids else " "
                    url = t.short_url or t.url or ""
                    url_part = f" ({url})" if url else ""
                    text_lines.append(f"    {done_marker} {t.name}{url_part}")
                    if include_desc and t.desc:
                        desc = (t.desc or "").strip()
                        if desc:
                            for line in desc.splitlines():
                                text_lines.append(f"      {line}")
            text_lines.append("")

        if resolved_fmt == OutputFormat.json:
            _write(json.dumps(json_rows, indent=2) + "\n", out_path=out_path)
        else:
            content = "\n".join(text_lines).rstrip() + "\n"
            _write(content, out_path=out_path)
        return None
    finally:
        client.close()


def _tasks_done(
    *,
    api_key: str | None,
    token: str | None,
    task_id: str,
    board_id: str | None,
    comment: str | None,
) -> None:
    resolved_api_key, resolved_token = _require_credentials(
        api_key=api_key, token=token
    )
    card_id = str(task_id)
    resolved_comment = comment or "Marked as done from Trello CLI."

    client = TrelloClient(api_key=resolved_api_key, token=resolved_token)
    try:
        task_name: str | None = None
        resolved_board_id: str | None = str(board_id) if board_id else None

        if resolved_board_id is None:
            card = client.fetch_card(card_id)
            if not isinstance(card, dict) or not isinstance(card.get("idBoard"), str):
                _die("Unable to determine board for this task/card id.")
            resolved_board_id = card["idBoard"]
            if isinstance(card.get("name"), str):
                task_name = card["name"]

        assert resolved_board_id is not None

        done_ids = _load_done_tasks(resolved_board_id)
        if card_id in done_ids:
            print("Already marked done locally.")
            return None

        done_ids.add(card_id)
        _save_done_tasks(resolved_board_id, done_ids)

        try:
            client.add_comment_to_card(card_id, resolved_comment)
        except Exception as e:
            print(f"Warning: failed to add Trello comment: {e}", file=sys.stderr)

        name_part = f" ({task_name})" if task_name else ""
        print(f"✓ Marked done{name_part}: {card_id}")
        return None
    finally:
        client.close()


app = typer.Typer(help="Trello CLI")
boards_app = typer.Typer(help="Board operations")
tasks_app = typer.Typer(help="Task operations")
app.add_typer(boards_app, name="boards")
app.add_typer(tasks_app, name="tasks")


@app.callback()
def _root(
    ctx: typer.Context,
    env_file: str | None = typer.Option(
        None,
        "--env-file",
        help="Path to a .env file (defaults to ./.env when present).",
    ),
    api_key: str | None = typer.Option(
        None, "--api-key", help="Trello API key (or set TRELLO_API_KEY)."
    ),
    token: str | None = typer.Option(
        None, "--token", help="Trello token (or set TRELLO_TOKEN)."
    ),
) -> None:
    """Initialize global CLI state (env + credentials)."""

    _load_env(env_file)
    ctx.ensure_object(dict)
    ctx.obj["api_key"] = api_key
    ctx.obj["token"] = token


@boards_app.command("list")
def boards_list(
    ctx: typer.Context,
    include_closed: bool = typer.Option(False, "--include-closed"),
    format: OutputFormat = typer.Option(OutputFormat.text, "--format"),
    out: str | None = typer.Option(None, "--out"),
) -> None:
    """List available Trello boards."""

    obj: dict[str, Any] = ctx.ensure_object(dict)
    _boards_list(
        api_key=obj.get("api_key"),
        token=obj.get("token"),
        include_closed=include_closed,
        fmt=format,
        out=out,
    )


@boards_app.command("link")
def boards_link(
    ctx: typer.Context,
    board_id: str = typer.Argument(..., help="Trello board ID"),
    path: str | None = typer.Option(
        None, "--path", help="Local path to link (defaults to current directory)."
    ),
) -> None:
    """Link a board to a local path."""

    obj: dict[str, Any] = ctx.ensure_object(dict)
    _boards_link(
        api_key=obj.get("api_key"),
        token=obj.get("token"),
        board_id=board_id,
        path=path,
    )


@boards_app.command("unlink")
def boards_unlink(board_id: str = typer.Argument(..., help="Trello board ID")) -> None:
    """Unlink a board."""

    _boards_unlink(board_id=board_id)


@boards_app.command("show")
def boards_show(
    ctx: typer.Context,
    format: OutputFormat = typer.Option(OutputFormat.text, "--format"),
    out: str | None = typer.Option(None, "--out"),
) -> None:
    """Show linked boards."""

    obj: dict[str, Any] = ctx.ensure_object(dict)
    _boards_show(
        api_key=obj.get("api_key"), token=obj.get("token"), fmt=format, out=out
    )


@tasks_app.command("fetch")
def tasks_fetch(
    ctx: typer.Context,
    board_id: str | None = typer.Option(
        None, "--board-id", help="Fetch from a specific board."
    ),
    include_closed: bool = typer.Option(False, "--include-closed"),
    include_done: bool = typer.Option(
        False, "--include-done", help="Include locally-marked done tasks in output."
    ),
    include_desc: bool = typer.Option(False, "--include-desc"),
    format: OutputFormat | None = typer.Option(None, "--format"),
    out: str | None = typer.Option(None, "--out"),
) -> None:
    """Fetch tasks (default: all linked boards)."""

    obj: dict[str, Any] = ctx.ensure_object(dict)
    _tasks_fetch(
        api_key=obj.get("api_key"),
        token=obj.get("token"),
        board_id=board_id,
        include_closed=include_closed,
        include_done=include_done,
        include_desc=include_desc,
        fmt=format,
        out=out,
        default_format=OutputFormat.json,
    )


@tasks_app.command("list")
def tasks_list(
    ctx: typer.Context,
    board_id: str | None = typer.Option(
        None, "--board-id", help="Fetch from a specific board."
    ),
    include_closed: bool = typer.Option(False, "--include-closed"),
    include_done: bool = typer.Option(
        False, "--include-done", help="Include locally-marked done tasks in output."
    ),
    include_desc: bool = typer.Option(False, "--include-desc"),
    format: OutputFormat | None = typer.Option(None, "--format"),
    out: str | None = typer.Option(None, "--out"),
) -> None:
    """List tasks (text output)."""

    obj: dict[str, Any] = ctx.ensure_object(dict)
    _tasks_fetch(
        api_key=obj.get("api_key"),
        token=obj.get("token"),
        board_id=board_id,
        include_closed=include_closed,
        include_done=include_done,
        include_desc=include_desc,
        fmt=format,
        out=out,
        default_format=OutputFormat.text,
    )


@tasks_app.command("done")
def tasks_done(
    ctx: typer.Context,
    task_id: str = typer.Argument(..., help="Trello card ID"),
    board_id: str | None = typer.Option(
        None,
        "--board-id",
        help="Board ID for local done storage (auto-detected if omitted).",
    ),
    comment: str | None = typer.Option(
        None,
        "--comment",
        help='Comment to post to Trello (default: "Marked as done from Trello CLI.").',
    ),
) -> None:
    """Mark a task as done."""

    obj: dict[str, Any] = ctx.ensure_object(dict)
    _tasks_done(
        api_key=obj.get("api_key"),
        token=obj.get("token"),
        task_id=task_id,
        board_id=board_id,
        comment=comment,
    )


def main(argv: list[str] | None = None) -> int:
    """Entry point for the `trello` script."""

    if argv is None:
        app()
        return 0  # pragma: no cover

    try:
        app(args=argv, standalone_mode=False)
    except typer.Exit as e:
        return int(e.exit_code)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

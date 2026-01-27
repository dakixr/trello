#!/usr/bin/env python3
"""Trello Fetcher - Trello CLI with board management and enhanced output."""

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

# Import from fetch_tasks module
from trello_fetcher import (
    TrelloClient,
    _cards_to_tasks,
    _parse_trello_datetime,
    _write_output,
    _load_env_from_path,
    _load_env,
    BoardConfig,
    _load_board_configs,
    _save_board_config,
    _load_done_tasks,
    _save_done_tasks,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Trello CLI: Fetch, manage boards, enhanced output",
        prog="trello"
    )
    
    # Environment
    parser.add_argument(
        "--env-file", help="Path to a .env file (defaults to ./.env when present)."
    )
    
    # Trello credentials
    parser.add_argument(
        "--api-key", default=None, help="Trello API key (or set TRELLO_API_KEY)."
    )
    parser.add_argument(
        "--token", default=None, help="Trello token (or set TRELLO_TOKEN)."
    )
    
    # Board and List selection
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
    
    # Output format
    parser.add_argument(
        "--format", choices=("json", "text"), default="json"
    )
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
    
    # link-board command
    link_parser = subparsers.add_parser("link-board", help="Link a Trello board to a local path")
    link_parser.add_argument("board-id", required=True, help="Trello board ID")
    link_parser.add_argument("--path", required=True, help="Local path to link (e.g., ~/Projects/ionisium)")
    
    # unlink-board command
    unlink_parser = subparsers.add_parser("unlink-board", help="Unlink a Trello board from local path")
    unlink_parser.add_argument("board-id", required=True, help="Trello board ID")
    
    # show-boards command
    show_parser = subparsers.add_parser("show-boards", help="Show all linked boards with their local paths")
    
    args = parser.parse_args(argv)
    _load_env(args.env_file)
    
    # Handle board management commands
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
    else:
        # Existing fetch logic for cards/boards
        if (args.list_id is None) == (args.board_id is None):
            raise SystemExit(
                "Provide exactly one of --list-id or --board-id (or set TRELLO_LIST_ID/TRELLO_BOARD_ID)."
            )

        out_path = Path(args.out).expanduser() if args.out else None

        client = TrelloClient(api_key=api_key, token=token)
        try:
            list_id_to_name: dict[str, str] = {}
            
            # Load board configs to get repo paths
            configs = _load_board_configs()
            
            if args.board_id is not None:
                # Single board mode: Fetch from specified board with repo path from config
                board_config = configs.get(args.board_id)
                if board_config and board_config.repo_path:
                    list_id_to_name[args.board_id] = board_config.repo_path
            
                cards = client.fetch_cards_for_board(
                    args.board_id, include_closed=args.include_closed
                )
            else:
                # Default mode: Fetch all boards and their lists
                boards = client.fetch_my_boards(include_closed=args.include_closed)
                for board in boards:
                    # Get board URL for display
                    if board.get("shortUrl"):
                        board_name = f"[{board['id']}]"
                    else:
                        board_name = board.get("name")
                    
                    # Store for later list ID resolution
                    list_id_to_name[board["id"]] = board_name
            
            # Fetch lists if board_id specified, otherwise get all boards
            if args.board_id is not None:
                lists = client.fetch_lists_for_board(args.board_id, include_closed=args.include_closed)
                try:
                    lst = lists[0] if isinstance(lists, list) else lists
                    if isinstance(lst, dict):
                        lst_id = lst.get("id")
                        lst_name = lst.get("name")
                        if isinstance(lst_id, str) and isinstance(lst_name, str):
                            list_id_to_name[lst_id] = lst_name
                except RuntimeError:
                    pass
            else:
                lists = client.fetch_lists_for_board(args.board_id, include_closed=args.include_closed)
                try:
                    for lst in lists:
                        if isinstance(lst, dict):
                            lst_id = lst.get("id")
                            lst_name = lst.get("name")
                            if isinstance(lst_id, str) and isinstance(lst_name, str):
                                list_id_to_name[lst_id] = lst_name
                except RuntimeError:
                    pass
        finally:
            client.close()

        tasks = _cards_to_tasks(cards, list_id_to_name=list_id_to_name)
        # Filter out completed tasks by default
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

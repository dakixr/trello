from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    Markdown,
    Static,
)

from .fetch_tasks import Task, TrelloClient, _cards_to_tasks, _load_env
from .list_boards import Board, _boards_to_models


# --- Config Management ---

CONFIG_DIR = Path.home() / ".config" / "trello_fetcher"
BOARDS_CONFIG_FILE = CONFIG_DIR / "boards.json"


@dataclass
class BoardConfig:
    """Configuration for a linked board."""

    board_id: str
    repo_path: str | None = None


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
            )
        return configs
    except (json.JSONDecodeError, OSError):
        return {}


def _save_board_config(board_id: str, repo_path: str | None) -> None:
    """Save a board configuration to disk."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    configs = _load_board_configs()
    if repo_path:
        configs[board_id] = BoardConfig(board_id=board_id, repo_path=repo_path)
    elif board_id in configs:
        del configs[board_id]

    data = {bid: {"repo_path": cfg.repo_path} for bid, cfg in configs.items()}
    BOARDS_CONFIG_FILE.write_text(json.dumps(data, indent=2))


@dataclass
class ListInfo:
    """Holds list metadata."""

    id: str
    name: str


class LinkRepoModal(ModalScreen[str | None]):
    """Modal dialog to link a board to a repository path."""

    CSS = """
    LinkRepoModal {
        align: center middle;
    }

    #link-container {
        width: 60%;
        height: auto;
        border: round $accent;
        padding: 1 2;
        background: $surface;
    }

    #link-title {
        text-align: center;
        text-style: bold;
        padding-bottom: 1;
    }

    #link-input {
        margin-bottom: 1;
    }

    #link-buttons {
        align: center middle;
    }

    #link-buttons Button {
        margin: 0 1;
    }
    """

    def __init__(self, board_name: str, current_path: str | None = None) -> None:
        super().__init__()
        self._board_name = board_name
        self._current_path = current_path or ""

    def compose(self) -> ComposeResult:
        with Vertical(id="link-container"):
            yield Static(f"Link repo for: {self._board_name}", id="link-title")
            yield Input(
                placeholder="Enter repository path (empty to unlink)",
                value=self._current_path,
                id="link-input",
            )
            with Horizontal(id="link-buttons"):
                yield Button("Save", variant="primary", id="save-btn")
                yield Button("Cancel", variant="default", id="cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-btn":
            input_widget = self.query_one("#link-input", Input)
            path = input_widget.value.strip()
            self.dismiss(path if path else None)
        else:
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        path = event.value.strip()
        self.dismiss(path if path else None)


class ScriptSelectModal(ModalScreen[list[Path]]):
    """Modal dialog to select scripts to run."""

    CSS = """
    ScriptSelectModal {
        align: center middle;
    }

    #script-container {
        width: 70%;
        height: auto;
        max-height: 80%;
        border: round $accent;
        padding: 1 2;
        background: $surface;
    }

    #script-title {
        text-align: center;
        text-style: bold;
        padding-bottom: 1;
    }

    #script-list {
        height: auto;
        max-height: 50vh;
        margin-bottom: 1;
    }

    .script-item {
        padding: 0 1;
    }

    .script-item-selected {
        background: $accent;
    }

    #script-buttons {
        align: center middle;
    }

    #script-buttons Button {
        margin: 0 1;
    }

    #script-hint {
        text-align: center;
        color: $text-muted;
        padding: 1 0;
    }
    """

    BINDINGS = [
        Binding("space", "toggle_select", "Toggle selection"),
        Binding("enter", "confirm", "Run selected"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, scripts: list[Path]) -> None:
        super().__init__()
        self._scripts = scripts
        self._selected: set[int] = set()

    def compose(self) -> ComposeResult:
        with Vertical(id="script-container"):
            yield Static("Select Scripts to Run", id="script-title")
            yield ListView(id="script-list")
            yield Static("Space: toggle | Enter: run | Esc: cancel", id="script-hint")
            with Horizontal(id="script-buttons"):
                yield Button("Run Selected", variant="primary", id="run-btn")
                yield Button("Cancel", variant="default", id="cancel-btn")

    def on_mount(self) -> None:
        script_list = self.query_one("#script-list", ListView)
        for i, script in enumerate(self._scripts):
            # Show location hint (repo-local vs global)
            if ".trello" in str(script):
                location = "repo"
            else:
                location = "global"
            label = Label(f"[ ] {script.name} ({location})", classes="script-item")
            item = ListItem(label)
            item.data = i  # type: ignore[attr-defined]
            script_list.append(item)
        if self._scripts:
            script_list.focus()

    def _update_item_display(self, index: int) -> None:
        script_list = self.query_one("#script-list", ListView)
        for item in script_list.query(ListItem):
            if hasattr(item, "data") and item.data == index:
                script = self._scripts[index]
                if ".trello" in str(script):
                    location = "repo"
                else:
                    location = "global"
                marker = "[●]" if index in self._selected else "[ ]"
                label = item.query_one(Label)
                label.update(f"{marker} {script.name} ({location})")
                if index in self._selected:
                    item.add_class("script-item-selected")
                else:
                    item.remove_class("script-item-selected")
                break

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        # Enter on ListView should run scripts, not toggle selection
        self.action_confirm()

    def action_toggle_select(self) -> None:
        script_list = self.query_one("#script-list", ListView)
        if script_list.highlighted_child and hasattr(
            script_list.highlighted_child, "data"
        ):
            index: int = script_list.highlighted_child.data  # type: ignore[attr-defined]
            if index in self._selected:
                self._selected.remove(index)
            else:
                self._selected.add(index)
            self._update_item_display(index)

    def action_confirm(self) -> None:
        if self._selected:
            # Run all selected scripts
            selected_scripts = [self._scripts[i] for i in sorted(self._selected)]
            self.dismiss(selected_scripts)
        else:
            # Nothing selected - run the highlighted script
            script_list = self.query_one("#script-list", ListView)
            if script_list.highlighted_child and hasattr(
                script_list.highlighted_child, "data"
            ):
                index: int = script_list.highlighted_child.data  # type: ignore[attr-defined]
                self.dismiss([self._scripts[index]])
            else:
                self.dismiss([])

    def action_cancel(self) -> None:
        self.dismiss([])

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "run-btn":
            self.action_confirm()
        else:
            self.action_cancel()


class BoardSelectScreen(Screen[tuple[Board, BoardConfig | None]]):
    """Screen to select a Trello board."""

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("l", "link_repo", "Link repo"),
    ]

    CSS = """
    BoardSelectScreen {
        align: center middle;
    }

    #board-container {
        width: 80%;
        height: 80%;
        border: round $accent;
        padding: 1 2;
    }

    #board-title {
        text-align: center;
        text-style: bold;
        color: $text;
        padding-bottom: 1;
    }

    #board-list {
        height: 1fr;
    }

    #loading-label {
        text-align: center;
        color: $text-muted;
    }

    .board-item {
        padding: 0 1;
    }
    """

    def __init__(self, client: TrelloClient) -> None:
        super().__init__()
        self._client = client
        self._boards: list[Board] = []
        self._board_configs: dict[str, BoardConfig] = {}
        self._highlighted_board: Board | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="board-container"):
            yield Static("Select a Board", id="board-title")
            yield Label("Loading boards...", id="loading-label")
            yield ListView(id="board-list")
        yield Footer()

    def on_mount(self) -> None:
        self._board_configs = _load_board_configs()
        self._load_boards()

    @work(thread=True)
    def _load_boards(self) -> None:
        try:
            boards_raw = self._client.fetch_my_boards(include_closed=False)
            self._boards = _boards_to_models(
                boards_raw if isinstance(boards_raw, list) else []
            )
        except Exception as e:
            self.app.call_from_thread(self._show_error, str(e))
            return

        self.app.call_from_thread(self._populate_boards)

    def _show_error(self, message: str) -> None:
        loading = self.query_one("#loading-label", Label)
        loading.update(f"Error: {message}")

    def _populate_boards(self) -> None:
        loading = self.query_one("#loading-label", Label)
        loading.display = False

        board_list = self.query_one("#board-list", ListView)
        board_list.clear()

        for board in self._boards:
            config = self._board_configs.get(board.id)
            linked_indicator = " [linked]" if config and config.repo_path else ""
            item = ListItem(
                Label(f"{board.name}{linked_indicator}", classes="board-item")
            )
            item.data = board  # type: ignore[attr-defined]
            board_list.append(item)

        if self._boards:
            board_list.focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if hasattr(event.item, "data"):
            board: Board = event.item.data  # type: ignore[attr-defined]
            config = self._board_configs.get(board.id)
            self.dismiss((board, config))

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.item and hasattr(event.item, "data"):
            self._highlighted_board = event.item.data  # type: ignore[attr-defined]
        else:
            self._highlighted_board = None

    def action_link_repo(self) -> None:
        if self._highlighted_board is None:
            self.app.notify("Select a board first.", severity="warning")
            return

        board = self._highlighted_board
        current_config = self._board_configs.get(board.id)
        current_path = current_config.repo_path if current_config else None

        def handle_link_result(path: str | None) -> None:
            if path is not None:
                # Validate path exists
                if path and not Path(path).is_dir():
                    self.app.notify(f"Path does not exist: {path}", severity="error")
                    return
                _save_board_config(board.id, path if path else None)
                self._board_configs = _load_board_configs()
                self._populate_boards()
                if path:
                    self.app.notify(f"Linked to: {path}")
                else:
                    self.app.notify("Repo unlinked.")

        self.app.push_screen(
            LinkRepoModal(board.name, current_path),
            handle_link_result,
        )

    def action_refresh(self) -> None:
        loading = self.query_one("#loading-label", Label)
        loading.update("Loading boards...")
        loading.display = True

        board_list = self.query_one("#board-list", ListView)
        board_list.clear()
        self._load_boards()


class TaskViewerScreen(Screen[None]):
    """Screen to view tasks organized by list with detail panel."""

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("b", "back", "Back to boards"),
        Binding("r", "refresh", "Refresh"),
        Binding("space", "toggle_select", "Select task"),
        Binding("d", "toggle_done", "Mark done"),
        Binding("c", "copy_task", "Copy task"),
        Binding("C", "copy_selected", "Copy selected"),
        Binding("x", "clear_selected", "Clear selected"),
        Binding("s", "run_script", "Run script"),
    ]

    CSS = """
    TaskViewerScreen {
        layout: grid;
        grid-size: 1;
        grid-rows: auto 1fr auto;
    }

    #main-container {
        height: 1fr;
    }

    #task-list-panel {
        width: 1fr;
        border: round $accent;
        padding: 0 1;
    }

    #task-detail-panel {
        width: 2fr;
        border: round $primary;
        padding: 1 2;
        overflow-y: auto;
    }

    #task-list {
        height: 1fr;
    }

    .list-separator {
        background: $accent;
        color: $text;
        text-style: bold;
        padding: 0 1;
        margin-top: 1;
    }

    .task-item {
        padding: 0 1;
    }

    .task-item-overdue {
        color: $error;
    }

    .task-item-done {
        text-style: italic strike;
        color: $text-muted;
    }

    #detail-title {
        text-style: bold;
        color: $accent;
        padding-bottom: 1;
    }

    #detail-meta {
        color: $text-muted;
        padding-bottom: 1;
    }

    #detail-labels {
        padding-bottom: 1;
    }

    .label-tag {
        background: $secondary;
        color: $text;
        padding: 0 1;
        margin-right: 1;
    }

    #detail-description {
        height: auto;
    }

    #loading-tasks {
        text-align: center;
        color: $text-muted;
        padding: 2;
    }

    #no-selection {
        text-align: center;
        color: $text-muted;
        padding: 2;
    }
    """

    def __init__(
        self,
        client: TrelloClient,
        board: Board,
        board_config: BoardConfig | None = None,
    ) -> None:
        super().__init__()
        self._client = client
        self._board = board
        self._board_config = board_config
        self._tasks: list[Task] = []
        self._lists: dict[str, str] = {}
        self._list_order: list[str] = []  # List IDs in Trello board order
        self._focused_task: Task | None = None
        self._selected_task_ids: set[str] = set()
        self._done_task_ids: set[str] = set()
        self._task_labels: dict[str, Label] = {}
        self._task_items: dict[str, ListItem] = {}

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main-container"):
            with Vertical(id="task-list-panel"):
                yield Label("Loading tasks...", id="loading-tasks")
                yield ListView(id="task-list")
            with Vertical(id="task-detail-panel"):
                yield Static("Select a task", id="no-selection")
                yield Static("", id="detail-title")
                yield Static("", id="detail-meta")
                yield Static("", id="detail-labels")
                yield Markdown("", id="detail-description")
        yield Footer()

    def on_mount(self) -> None:
        self.title = f"Board: {self._board.name}"
        self._load_tasks()

    @work(thread=True)
    def _load_tasks(self) -> None:
        try:
            # Fetch lists first
            lists_raw = self._client.fetch_lists_for_board(
                self._board.id, include_closed=False
            )
            self._list_order = []
            if isinstance(lists_raw, list):
                for lst in lists_raw:
                    if isinstance(lst, dict):
                        lst_id = lst.get("id")
                        lst_name = lst.get("name")
                        if isinstance(lst_id, str) and isinstance(lst_name, str):
                            self._lists[lst_id] = lst_name
                            self._list_order.append(lst_id)

            # Fetch cards
            cards_raw = self._client.fetch_cards_for_board(
                self._board.id, include_closed=False
            )
            self._tasks = _cards_to_tasks(
                cards_raw if isinstance(cards_raw, list) else [],
                list_id_to_name=self._lists,
            )
            # Filter out closed tasks
            self._tasks = [
                t for t in self._tasks if not t.closed and not t.due_complete
            ]

        except Exception as e:
            self.app.call_from_thread(self._show_error, str(e))
            return

        self.app.call_from_thread(self._populate_tasks)

    def _show_error(self, message: str) -> None:
        loading = self.query_one("#loading-tasks", Label)
        loading.update(f"Error: {message}")

    def _populate_tasks(self) -> None:
        loading = self.query_one("#loading-tasks", Label)
        loading.display = False

        task_list = self.query_one("#task-list", ListView)
        task_list.clear()
        self._task_labels.clear()
        self._task_items.clear()
        self._selected_task_ids.clear()
        self._done_task_ids.clear()
        self._focused_task = None

        # Group tasks by list_id
        tasks_by_list_id: dict[str, list[Task]] = {}
        for task in self._tasks:
            list_id = task.list_id or "unknown"
            if list_id not in tasks_by_list_id:
                tasks_by_list_id[list_id] = []
            tasks_by_list_id[list_id].append(task)

        # Use reverse Trello board order for lists
        ordered_list_ids = list(reversed(self._list_order))
        # Add any lists not in _list_order (shouldn't happen, but be safe)
        for list_id in tasks_by_list_id:
            if list_id not in ordered_list_ids:
                ordered_list_ids.append(list_id)

        # Add tasks to list with separators
        for list_id in ordered_list_ids:
            if list_id not in tasks_by_list_id:
                continue
            tasks = tasks_by_list_id[list_id]
            list_name = self._lists.get(list_id, "Unknown")

            # Add separator
            separator = ListItem(
                Label(f"--- {list_name} ---", classes="list-separator")
            )
            separator.disabled = True
            task_list.append(separator)

            # Add tasks
            for task in tasks:
                label = Label(self._format_task_label(task), classes="task-item")
                item = ListItem(label)
                item.data = task  # type: ignore[attr-defined]
                task_list.append(item)
                self._task_labels[task.id] = label
                self._task_items[task.id] = item

        if self._tasks:
            task_list.focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if hasattr(event.item, "data"):
            task: Task = event.item.data  # type: ignore[attr-defined]
            self._show_task_detail(task)
        else:
            self._focused_task = None

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.item and hasattr(event.item, "data"):
            task: Task = event.item.data  # type: ignore[attr-defined]
            self._focused_task = task
            self._show_task_detail(task)
        else:
            self._focused_task = None

    def _show_task_detail(self, task: Task) -> None:
        no_selection = self.query_one("#no-selection", Static)
        no_selection.display = False

        title = self.query_one("#detail-title", Static)
        title.update(task.name)

        meta_parts: list[str] = []
        if task.list_name:
            meta_parts.append(f"List: {task.list_name}")
        if task.due:
            meta_parts.append(f"Due: {task.due}")
        if task.short_url:
            meta_parts.append(f"URL: {task.short_url}")

        meta = self.query_one("#detail-meta", Static)
        meta.update(" | ".join(meta_parts) if meta_parts else "")

        labels = self.query_one("#detail-labels", Static)
        if task.labels:
            labels.update("Labels: " + ", ".join(task.labels))
        else:
            labels.update("")

        description = self.query_one("#detail-description", Markdown)
        description.update(task.desc or "_No description_")

    def _format_task_label(self, task: Task) -> str:
        # Show done marker if locally marked as done
        if task.id in self._done_task_ids:
            done_marker = "[✓]"
        else:
            done_marker = "[ ]"
        select_marker = "●" if task.id in self._selected_task_ids else " "
        return f"{done_marker} {select_marker} {task.name}"

    def _toggle_task_selection(self, task: Task) -> None:
        if task.id in self._selected_task_ids:
            self._selected_task_ids.remove(task.id)
        else:
            self._selected_task_ids.add(task.id)

        label = self._task_labels.get(task.id)
        if label is not None:
            label.update(self._format_task_label(task))

    def _copy_tasks_to_clipboard(self, tasks: list[Task]) -> None:
        if not tasks:
            self.app.notify("No tasks to copy.", severity="warning")
            return

        blocks: list[str] = []
        for task in tasks:
            description = (task.desc or "").strip()
            blocks.append(f"{task.name}\n{description}")

        payload = "\n\n---\n\n".join(blocks)
        self.app.copy_to_clipboard(payload)
        self.app.notify(f"Copied {len(tasks)} task(s) to clipboard.")

    def action_toggle_select(self) -> None:
        if self._focused_task is None:
            self.app.notify("Select a task to toggle.", severity="warning")
            return

        self._toggle_task_selection(self._focused_task)

    def action_toggle_done(self) -> None:
        """Toggle the local 'done' state of the focused task."""
        if self._focused_task is None:
            self.app.notify("Select a task to mark as done.", severity="warning")
            return

        task = self._focused_task
        was_done = task.id in self._done_task_ids

        # Toggle local state
        if was_done:
            self._done_task_ids.remove(task.id)
        else:
            self._done_task_ids.add(task.id)

        # Update label text
        label = self._task_labels.get(task.id)
        if label is not None:
            label.update(self._format_task_label(task))

        # Update CSS class on the ListItem for styling
        item = self._task_items.get(task.id)
        if item is not None:
            if task.id in self._done_task_ids:
                item.add_class("task-item-done")
            else:
                item.remove_class("task-item-done")

        # Post a comment to Trello in background
        self._post_done_comment(task.id, task.name, not was_done)

    @work(thread=True)
    def _post_done_comment(
        self, card_id: str, task_name: str, marked_done: bool
    ) -> None:
        """Post a comment to Trello indicating the task was marked done/undone."""
        if marked_done:
            comment = "Marked as done from Trello TUI."
        else:
            comment = "Unmarked as done from Trello TUI."

        try:
            self._client.add_comment_to_card(card_id, comment)
            self.app.call_from_thread(
                self.app.notify,
                f"Comment added: {task_name}",
            )
        except Exception as e:
            self.app.call_from_thread(
                self.app.notify,
                f"Failed to add comment: {e}",
                severity="error",
            )

    def action_copy_task(self) -> None:
        if self._focused_task is None:
            self.app.notify("Select a task to copy.", severity="warning")
            return

        self._copy_tasks_to_clipboard([self._focused_task])

    def action_copy_selected(self) -> None:
        if self._selected_task_ids:
            tasks = [task for task in self._tasks if task.id in self._selected_task_ids]
            self._copy_tasks_to_clipboard(tasks)
            return

        if self._focused_task is None:
            self.app.notify("Select tasks to copy.", severity="warning")
            return

        self._copy_tasks_to_clipboard([self._focused_task])

    def action_clear_selected(self) -> None:
        if not self._selected_task_ids:
            self.app.notify("No selected tasks to clear.", severity="warning")
            return

        self._selected_task_ids.clear()
        for task in self._tasks:
            label = self._task_labels.get(task.id)
            if label is not None:
                label.update(self._format_task_label(task))

    def action_back(self) -> None:
        self.dismiss()

    def action_refresh(self) -> None:
        loading = self.query_one("#loading-tasks", Label)
        loading.update("Loading tasks...")
        loading.display = True

        task_list = self.query_one("#task-list", ListView)
        task_list.clear()
        self._load_tasks()

    def _find_all_scripts(self) -> list[Path]:
        """Find all available scripts from repo-local and global locations."""
        scripts: list[Path] = []

        # Check repo-local scripts
        if self._board_config and self._board_config.repo_path:
            repo_path = Path(self._board_config.repo_path)
            trello_dir = repo_path / ".trello"
            if trello_dir.is_dir():
                for script_path in trello_dir.iterdir():
                    if script_path.is_file() and script_path.suffix in (".sh", ".py"):
                        scripts.append(script_path)

        # Check global scripts
        if CONFIG_DIR.is_dir():
            for script_path in CONFIG_DIR.iterdir():
                if script_path.is_file() and script_path.suffix in (".sh", ".py"):
                    scripts.append(script_path)

        return scripts

    def _build_script_env(self, task: Task) -> dict[str, str]:
        """Build environment variables for script execution."""
        env = os.environ.copy()

        # Task fields
        env["TASK_ID"] = task.id
        env["TASK_NAME"] = task.name
        env["TASK_DESC"] = task.desc or ""
        env["TASK_URL"] = task.url or ""
        env["TASK_SHORT_URL"] = task.short_url or ""
        env["TASK_DUE"] = task.due or ""
        env["TASK_DUE_COMPLETE"] = "true" if task.due_complete else "false"
        env["TASK_LIST_ID"] = task.list_id or ""
        env["TASK_LIST_NAME"] = task.list_name or ""
        env["TASK_LABELS"] = ",".join(task.labels)
        env["TASK_LAST_ACTIVITY"] = task.last_activity or ""
        env["TASK_CLOSED"] = "true" if task.closed else "false"

        # Board fields
        env["BOARD_ID"] = self._board.id
        env["BOARD_NAME"] = self._board.name

        # Repo path
        if self._board_config and self._board_config.repo_path:
            env["REPO_PATH"] = self._board_config.repo_path

        return env

    def action_run_script(self) -> None:
        """Show script selection modal and run selected scripts."""
        if self._focused_task is None:
            self.app.notify("Select a task first.", severity="warning")
            return

        scripts = self._find_all_scripts()
        if not scripts:
            self.app.notify(
                "No scripts found. Create .trello/*.sh or *.py in your repo, "
                "or add scripts to ~/.config/trello_fetcher/",
                severity="warning",
            )
            return

        task = self._focused_task

        def handle_script_selection(selected: list[Path]) -> None:
            if not selected:
                return
            for script_path in selected:
                self.app.notify(f"Launching {script_path.name}...")
                self._execute_script(script_path, task)

        self.app.push_screen(ScriptSelectModal(scripts), handle_script_selection)

    @work(thread=True)
    def _execute_script(self, script_path: Path, task: Task) -> None:
        """Execute the script in a new Ghostty terminal window."""
        env = self._build_script_env(task)
        cwd = self._board_config.repo_path if self._board_config else str(Path.home())

        try:
            # Build export statements for environment variables
            exports = []
            for key, value in env.items():
                if key.startswith(("TASK_", "BOARD_", "REPO_")):
                    # Escape single quotes in values
                    escaped_value = value.replace("'", "'\"'\"'")
                    exports.append(f"export {key}='{escaped_value}'")

            exports_str = "; ".join(exports)

            # Determine how to run the script
            if script_path.suffix == ".py":
                script_cmd = f"python '{script_path}'"
            else:
                script_cmd = f"'{script_path}'"

            # Build the full command to run in Ghostty
            # cd to cwd, export env vars, run script, then keep shell open on error
            full_cmd = f"cd '{cwd}' && {exports_str}; {script_cmd}"

            # Launch in Ghostty
            subprocess.Popen(
                ["ghostty", "-e", "bash", "-c", full_cmd],
                start_new_session=True,
            )

            self.app.call_from_thread(
                self.app.notify, f"Launched {script_path.name} in Ghostty"
            )

        except FileNotFoundError:
            self.app.call_from_thread(
                self.app.notify,
                "Ghostty not found. Install it or add to PATH.",
                severity="error",
            )
        except Exception as e:
            self.app.call_from_thread(
                self.app.notify, f"Failed to launch: {e}", severity="error"
            )


class TrelloTUI(App[None]):
    """Trello Task Viewer TUI Application."""

    TITLE = "Trello Task Viewer"

    CSS = """
    Screen {
        background: $surface;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, client: TrelloClient) -> None:
        super().__init__()
        self._client = client

    def on_mount(self) -> None:
        self.push_screen(BoardSelectScreen(self._client), self._on_board_selected)

    def _on_board_selected(
        self, result: tuple[Board, BoardConfig | None] | None
    ) -> None:
        if result is not None:
            board, board_config = result
            self.push_screen(
                TaskViewerScreen(self._client, board, board_config),
                self._on_task_viewer_closed,
            )

    def _on_task_viewer_closed(self, _result: None) -> None:
        # Go back to board selection
        self.push_screen(BoardSelectScreen(self._client), self._on_board_selected)


def main() -> int:
    """Entry point for the TUI."""
    _load_env(None)

    api_key = os.getenv("TRELLO_API_KEY")
    token = os.getenv("TRELLO_TOKEN")

    if not api_key or not token:
        raise SystemExit(
            "Missing Trello credentials. Set TRELLO_API_KEY and TRELLO_TOKEN in .env or environment."
        )

    client = TrelloClient(api_key=api_key, token=token)
    try:
        app = TrelloTUI(client)
        app.run()
    finally:
        client.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

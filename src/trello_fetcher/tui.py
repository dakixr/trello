from __future__ import annotations

import os
from dataclasses import dataclass

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import (
    Footer,
    Header,
    Label,
    ListItem,
    ListView,
    Markdown,
    Static,
)

from .fetch_tasks import Task, TrelloClient, _cards_to_tasks, _load_env
from .list_boards import Board, _boards_to_models


@dataclass
class ListInfo:
    """Holds list metadata."""

    id: str
    name: str


class BoardSelectScreen(Screen[Board]):
    """Screen to select a Trello board."""

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
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

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="board-container"):
            yield Static("Select a Board", id="board-title")
            yield Label("Loading boards...", id="loading-label")
            yield ListView(id="board-list")
        yield Footer()

    def on_mount(self) -> None:
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
            item = ListItem(Label(board.name, classes="board-item"))
            item.data = board  # type: ignore[attr-defined]
            board_list.append(item)

        if self._boards:
            board_list.focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if hasattr(event.item, "data"):
            board: Board = event.item.data  # type: ignore[attr-defined]
            self.dismiss(board)

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

    def __init__(self, client: TrelloClient, board: Board) -> None:
        super().__init__()
        self._client = client
        self._board = board
        self._tasks: list[Task] = []
        self._lists: dict[str, str] = {}
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
            if isinstance(lists_raw, list):
                for lst in lists_raw:
                    if isinstance(lst, dict):
                        lst_id = lst.get("id")
                        lst_name = lst.get("name")
                        if isinstance(lst_id, str) and isinstance(lst_name, str):
                            self._lists[lst_id] = lst_name

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

        # Group tasks by list
        tasks_by_list: dict[str, list[Task]] = {}
        for task in self._tasks:
            list_name = task.list_name or "Unknown"
            if list_name not in tasks_by_list:
                tasks_by_list[list_name] = []
            tasks_by_list[list_name].append(task)

        # Add tasks to list with separators
        for list_name, tasks in tasks_by_list.items():
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

    def _on_board_selected(self, board: Board | None) -> None:
        if board is not None:
            self.push_screen(
                TaskViewerScreen(self._client, board),
                self._on_task_viewer_closed,
            )

    def _on_task_viewer_closed(self, result: None) -> None:
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

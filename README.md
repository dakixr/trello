## Trello task fetcher

Examples:
```bash
# costcompiler
uv run python -m trello_fetcher --board-id 663b9ea742a172687515c3f3 --format text
uv run python -m trello_fetcher --board-id 663b9ea742a172687515c3f3 --format text --include-desc
```


Fetch “tasks” (Trello cards) from a Trello **list** or **board** using a local `.env` file.

### Setup

- Copy `env.example` to `.env` and fill in values.
- Install deps (example with `uv`):

```bash
uv sync
```

### Run

- **List your boards** (to find IDs):

```bash
uv run python -m trello_fetcher.list_boards --format text
```

- **Fetch cards from a list**:

```bash
python3 fetch_trello_tasks.py --list-id YOUR_LIST_ID --format json --out trello_tasks.json
```

- **Fetch cards from a board**:

```bash
python3 fetch_trello_tasks.py --board-id YOUR_BOARD_ID --format text
```

### Environment variables

- **TRELLO_API_KEY**: your Trello API key
- **TRELLO_TOKEN**: your Trello token
- **TRELLO_LIST_ID**: list to fetch (optional if passing `--list-id`)
- **TRELLO_BOARD_ID**: board to fetch (optional if passing `--board-id`)




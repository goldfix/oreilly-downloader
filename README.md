# O'Reilly epub downloader

O'Reilly provides all of their books in epub format, but only through their own
reader.

This script allows you to download all the individual files and assemble them
back into a full epub. This allows you to use other readers, e.g. for
accessibility reasons.

You need a valid JWT to download content. If you do not provide one, each
chapter will be cut short. You can get it by logging in with your browser and
extracting the `orm-jwt` cookie using the developer tools.

Before any usage, please read the [O'Reilly Terms of
Service](https://learning.oreilly.com/terms/).

# Usage

## Setup

The project uses `uv` for dependency management (Python 3.12):

```bash
source py_env.sh init 3.12   # create .venv and install dependencies
source py_env.sh active      # activate .venv and load py_var.sh
```

## Providing the JWT token

The token is resolved in this priority order:

1. `--jwt` CLI argument;
2. `OREILLY_JWT` environment variable (e.g. from a `.env` file next to the
   project — `.env` is ignored by git).

```bash
# Option A: pass the token explicitly
uv run python oreilly_downloader.py 9781491958698 --jwt 'XYZ'

# Option B: store it in .env (recommended, keeps it out of shell history)
echo 'OREILLY_JWT=XYZ' >> .env
uv run python oreilly_downloader.py 9781491958698
```

## Options

| Option | Description | Default |
|---|---|---|
| `book_id` | Book ID, ISBN, `urn:orm:book:...`, or full O'Reilly URL | required |
| `--jwt` | O'Reilly `orm-jwt` cookie value | `OREILLY_JWT` from `.env` |
| `-o, --output` | Output file or directory path | `<book_id>.epub` |
| `-c, --concurrency` | Maximum concurrent file downloads | `10` |

```bash
uv run python oreilly_downloader.py https://learning.oreilly.com/library/view/fluent-python-2nd/9781492056348/ -o out/ -c 5
```

# Contributing

I am not really interested in adding any major features to this project. I will
accept fixes, but nothing that adds a significant amount of new code.

If you feel like something is missing, feel free to fork. You may also look at
rejected pull requests, maybe someone already worked on something similar.

# Similar Projects

-   <https://github.com/lorenzodifuccia/safaribooks> (python)
-   <https://github.com/hurlenko/orly> (rust)
-   <https://github.com/jenni/obooks> (javascript)
-   <https://github.com/rahulvramesh/oreilly-books-grabber> (go)

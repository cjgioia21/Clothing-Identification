"""``python -m pokedeck`` — the CLI with arguments, the menu without."""

from __future__ import annotations

import multiprocessing
import sys

from pokedeck.app import main as app_main
from pokedeck.console import use_utf8
from pokedeck.cli import main as cli_main

COMMANDS = ("check", "sim", "hand", "odds", "compare", "gauntlet")


def main(argv: list[str] | None = None) -> int:
    multiprocessing.freeze_support()
    use_utf8()  # a packaged executable re-runs itself for workers
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and (arguments[0] in COMMANDS or arguments[0].startswith("-")):
        return cli_main(arguments)
    return app_main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())

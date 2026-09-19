"""Entry point for the packaged executable.

PyInstaller runs its entry script as ``__main__`` with no package around it, so
the launcher imports pokedeck by its absolute name and hands over.
"""

import multiprocessing

from pokedeck.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())

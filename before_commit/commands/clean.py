from __future__ import annotations

import os.path

from before_commit import output
from before_commit.store import Store
from before_commit.util import rmtree


def clean(store: Store) -> int:
    legacy_path = os.path.expanduser('~/.pre-commit')
    for directory in (store.directory, legacy_path):
        if os.path.exists(directory):
            rmtree(directory)
            output.write_line(f'Cleaned {directory}.')
    return 0

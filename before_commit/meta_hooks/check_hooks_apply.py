from __future__ import annotations

import argparse
from typing import Sequence

import before_commit.constants as C
from before_commit import git
from before_commit.clientlib import load_config
from before_commit.commands.run import Classifier
from before_commit.repository import all_hooks
from before_commit.store import Store


def check_all_hooks_match_files(config_file: str) -> int:
    config = load_config(config_file)
    classifier = Classifier.from_config(
        git.get_all_files(), config['files'], config['exclude'],
    )
    retv = 0

    for hook in all_hooks(config, Store()):
        if hook.always_run or hook.language == 'fail':
            continue
        elif not classifier.filenames_for_hook(hook):
            print(f'{hook.id} does not apply to this repository')
            retv = 1

    return retv


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('filenames', nargs='*', default=[C.CONFIG_FILE])
    args = parser.parse_args(argv)

    retv = 0
    for filename in args.filenames:
        retv |= check_all_hooks_match_files(filename)
    return retv


if __name__ == '__main__':
    raise SystemExit(main())

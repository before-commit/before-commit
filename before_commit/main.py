from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Sequence

import before_commit.constants as C
from before_commit import git
from before_commit.color import add_color_option
from before_commit.commands.autoupdate import autoupdate
from before_commit.commands.clean import clean
from before_commit.commands.gc import gc
from before_commit.commands.hook_impl import hook_impl
from before_commit.commands.init_templatedir import init_templatedir
from before_commit.commands.install_uninstall import install
from before_commit.commands.install_uninstall import install_hooks
from before_commit.commands.install_uninstall import uninstall
from before_commit.commands.migrate_config import migrate_config
from before_commit.commands.run import run
from before_commit.commands.sample_config import sample_config
from before_commit.commands.try_repo import try_repo
from before_commit.commands.validate_config import validate_config
from before_commit.commands.validate_manifest import validate_manifest
from before_commit.error_handler import error_handler
from before_commit.logging_handler import logging_handler
from before_commit.store import Store


logger = logging.getLogger('before_commit')

# https://github.com/pre-commit/pre-commit/issues/217
# On OSX, making a virtualenv using pyvenv at . causes `virtualenv` and `pip`
# to install packages to the wrong place.  We don't want anything to deal with
# pyvenv
os.environ.pop('__PYVENV_LAUNCHER__', None)

COMMANDS_NO_GIT = {
    'clean', 'gc', 'init-templatedir', 'sample-config',
    'validate-config', 'validate-manifest',
}


def _add_config_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        '-c', '--config', default='',
        help='Path to alternate config file.  Empty fallbacks to defaults.',
    )


def _add_hook_type_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        '-t', '--hook-type',
        choices=C.HOOK_TYPES, action='append', dest='hook_types',
    )


def _add_run_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('hook', nargs='?', help='A single hook-id to run')
    parser.add_argument('--verbose', '-v', action='store_true', default=False)
    mutex_group = parser.add_mutually_exclusive_group(required=False)
    mutex_group.add_argument(
        '--all-files', '-a', action='store_true', default=False,
        help='Run on all the files in the repo.',
    )
    mutex_group.add_argument(
        '--fail-fast', action='store_true',
        help='Stop running hooks after the first failure',
    )
    mutex_group.add_argument(
        '--files', nargs='*', default=[],
        help='Specific filenames to run hooks on.',
    )
    parser.add_argument(
        '--show-diff-on-failure', action='store_true',
        help='When hooks fail, run `git diff` directly afterward.',
    )
    parser.add_argument(
        '--hook-stage', choices=C.STAGES, default='commit',
        help='The stage during which the hook is fired.  One of %(choices)s',
    )
    parser.add_argument(
        '--remote-branch', help='Remote branch ref used by `git push`.',
    )
    parser.add_argument(
        '--local-branch', help='Local branch ref used by `git push`.',
    )
    parser.add_argument(
        '--from-ref', '--source', '-s',
        help=(
            '(for usage with `--to-ref`) -- this option represents the '
            'original ref in a `from_ref...to_ref` diff expression.  '
            'For `pre-push` hooks, this represents the branch you are pushing '
            'to.  '
            'For `post-checkout` hooks, this represents the branch that was '
            'previously checked out.'
        ),
    )
    parser.add_argument(
        '--to-ref', '--origin', '-o',
        help=(
            '(for usage with `--from-ref`) -- this option represents the '
            'destination ref in a `from_ref...to_ref` diff expression.  '
            'For `pre-push` hooks, this represents the branch being pushed.  '
            'For `post-checkout` hooks, this represents the branch that is '
            'now checked out.'
        ),
    )
    parser.add_argument(
        '--commit-msg-filename',
        help='Filename to check when running during `commit-msg`',
    )
    parser.add_argument(
        '--prepare-commit-message-source',
        help=(
            'Source of the commit message '
            '(typically the second argument to .git/hooks/prepare-commit-msg)'
        ),
    )
    parser.add_argument(
        '--commit-object-name',
        help=(
            'Commit object name '
            '(typically the third argument to .git/hooks/prepare-commit-msg)'
        ),
    )
    parser.add_argument(
        '--remote-name', help='Remote name used by `git push`.',
    )
    parser.add_argument('--remote-url', help='Remote url used by `git push`.')
    parser.add_argument(
        '--checkout-type',
        help=(
            'Indicates whether the checkout was a branch checkout '
            '(changing branches, flag=1) or a file checkout (retrieving a '
            'file from the index, flag=0).'
        ),
    )
    parser.add_argument(
        '--is-squash-merge',
        help=(
            'During a post-merge hook, indicates whether the merge was a '
            'squash merge'
        ),
    )
    parser.add_argument(
        '--rewrite-command',
        help=(
            'During a post-rewrite hook, specifies the command that invoked '
            'the rewrite'
        ),
    )


def _guess_config_file(args: argparse.Namespace) -> None:
    if args.config != '':
        return
    default_ret = C.DEFAULT_CONFIG_FILE
    found = 0
    for file in C.CONFIG_FILES:
        if os.path.exists(file):
            args.config = file
            found += 1
            if found == 1:
                default_ret = file
            if found > 1:
                logger.warning('Duplicate config file \'%s\'', file)
    if found > 1:
        logger.warning('Fallback to \'%s\'', C.DEFAULT_CONFIG_FILE)
        args.config = default_ret
    if not found:
        args.config = default_ret


def _adjust_args_and_chdir(args: argparse.Namespace) -> None:
    # `--config` was specified relative to the non-root working directory
    if os.path.exists(args.config):
        args.config = os.path.abspath(args.config)

    if args.command in {'run', 'try-repo'}:
        args.files = [os.path.abspath(filename) for filename in args.files]
    if args.command == 'try-repo' and os.path.exists(args.repo):
        args.repo = os.path.abspath(args.repo)

    toplevel = git.get_root()
    os.chdir(toplevel)

    if os.path.isfile(args.config):
        args.config = os.path.relpath(args.config)
    if args.command in {'run', 'try-repo'}:
        args.files = [os.path.relpath(filename) for filename in args.files]
    if args.command == 'try-repo' and os.path.exists(args.repo):
        args.repo = os.path.relpath(args.repo)


def main(argv: Sequence[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(prog='pre-commit')

    # https://stackoverflow.com/a/8521644/812183
    parser.add_argument(
        '-V', '--version',
        action='version',
        version=f'%(prog)s {C.VERSION}',
    )

    subparsers = parser.add_subparsers(dest='command')

    def _add_cmd(name: str, *, help: str) -> argparse.ArgumentParser:
        parser = subparsers.add_parser(name, help=help)
        add_color_option(parser)
        return parser

    autoupdate_parser = _add_cmd(
        'autoupdate',
        help="Auto-update pre-commit config to the latest repos' versions.",
    )
    _add_config_option(autoupdate_parser)
    autoupdate_parser.add_argument(
        '--bleeding-edge', action='store_true',
        help=(
            'Update to the bleeding edge of `HEAD` instead of the latest '
            'tagged version (the default behavior).'
        ),
    )
    autoupdate_parser.add_argument(
        '--freeze', action='store_true',
        help='Store "frozen" hashes in `rev` instead of tag names',
    )
    autoupdate_parser.add_argument(
        '--repo', dest='repos', action='append', metavar='REPO',
        help='Only update this repository -- may be specified multiple times.',
    )

    _add_cmd('clean', help='Clean out pre-commit files.')

    _add_cmd('gc', help='Clean unused cached repos.')

    init_templatedir_parser = _add_cmd(
        'init-templatedir',
        help=(
            'Install hook script in a directory intended for use with '
            '`git config init.templateDir`.'
        ),
    )
    _add_config_option(init_templatedir_parser)
    init_templatedir_parser.add_argument(
        'directory', help='The directory in which to write the hook script.',
    )
    init_templatedir_parser.add_argument(
        '--no-allow-missing-config',
        action='store_false',
        dest='allow_missing_config',
        help='Assume cloned repos should have a `pre-commit` config.',
    )
    _add_hook_type_option(init_templatedir_parser)

    install_parser = _add_cmd('install', help='Install the pre-commit script.')
    _add_config_option(install_parser)
    install_parser.add_argument(
        '-f', '--overwrite', action='store_true',
        help='Overwrite existing hooks / remove migration mode.',
    )
    install_parser.add_argument(
        '--install-hooks', action='store_true',
        help=(
            'Whether to install hook environments for all environments '
            'in the config file.'
        ),
    )
    _add_hook_type_option(install_parser)
    install_parser.add_argument(
        '--allow-missing-config', action='store_true', default=False,
        help=(
            'Whether to allow a missing `pre-commit` configuration file '
            'or exit with a failure code.'
        ),
    )

    install_hooks_parser = _add_cmd(
        'install-hooks',
        help=(
            'Install hook environments for all environments in the config '
            'file.  You may find `pre-commit install --install-hooks` more '
            'useful.'
        ),
    )
    _add_config_option(install_hooks_parser)

    migrate_config_parser = _add_cmd(
        'migrate-config',
        help='Migrate list configuration to new map configuration.',
    )
    _add_config_option(migrate_config_parser)

    run_parser = _add_cmd('run', help='Run hooks.')
    _add_config_option(run_parser)
    _add_run_options(run_parser)

    _add_cmd(
        'sample-config',
        help=f'Produce a sample {C.DEFAULT_CONFIG_FILE} file',
    )

    try_repo_parser = _add_cmd(
        'try-repo',
        help='Try the hooks in a repository, useful for developing new hooks.',
    )
    _add_config_option(try_repo_parser)
    try_repo_parser.add_argument(
        'repo', help='Repository to source hooks from.',
    )
    try_repo_parser.add_argument(
        '--ref', '--rev',
        help=(
            'Manually select a rev to run against, otherwise the `HEAD` '
            'revision will be used.'
        ),
    )
    _add_run_options(try_repo_parser)

    uninstall_parser = _add_cmd(
        'uninstall', help='Uninstall the pre-commit script.',
    )
    _add_config_option(uninstall_parser)
    _add_hook_type_option(uninstall_parser)

    validate_config_parser = _add_cmd(
        'validate-config', help='Validate .pre-commit-config.yaml files',
    )
    validate_config_parser.add_argument('filenames', nargs='*')

    validate_manifest_parser = _add_cmd(
        'validate-manifest', help='Validate .pre-commit-hooks.yaml files',
    )
    validate_manifest_parser.add_argument('filenames', nargs='*')

    # does not use `_add_cmd` because it doesn't use `--color`
    help = subparsers.add_parser(
        'help', help='Show help for a specific command.',
    )
    help.add_argument('help_cmd', nargs='?', help='Command to show help for.')

    # not intended for users to call this directly
    hook_impl_parser = subparsers.add_parser('hook-impl')
    add_color_option(hook_impl_parser)
    _add_config_option(hook_impl_parser)
    hook_impl_parser.add_argument('--hook-type')
    hook_impl_parser.add_argument('--hook-dir')
    hook_impl_parser.add_argument(
        '--skip-on-missing-config', action='store_true',
    )
    hook_impl_parser.add_argument(dest='rest', nargs=argparse.REMAINDER)

    # argparse doesn't really provide a way to use a `default` subparser
    if len(argv) == 0:
        argv = ['run']
    args = parser.parse_args(argv)

    if args.command == 'help' and args.help_cmd:
        parser.parse_args([args.help_cmd, '--help'])
    elif args.command == 'help':
        parser.parse_args(['--help'])

    with error_handler(), logging_handler(args.color):
        git.check_for_cygwin_mismatch()

        _guess_config_file(args)

        store = Store()

        if args.command not in COMMANDS_NO_GIT:
            _adjust_args_and_chdir(args)
            store.mark_config_used(args.config)

        if args.command == 'autoupdate':
            return autoupdate(
                args.config, store,
                tags_only=not args.bleeding_edge,
                freeze=args.freeze,
                repos=args.repos,
            )
        elif args.command == 'clean':
            return clean(store)
        elif args.command == 'gc':
            return gc(store)
        elif args.command == 'hook-impl':
            return hook_impl(
                store,
                config=args.config,
                color=args.color,
                hook_type=args.hook_type,
                hook_dir=args.hook_dir,
                skip_on_missing_config=args.skip_on_missing_config,
                args=args.rest[1:],
            )
        elif args.command == 'install':
            return install(
                args.config, store,
                hook_types=args.hook_types,
                overwrite=args.overwrite,
                hooks=args.install_hooks,
                skip_on_missing_config=args.allow_missing_config,
            )
        elif args.command == 'init-templatedir':
            return init_templatedir(
                args.config, store, args.directory,
                hook_types=args.hook_types,
                skip_on_missing_config=args.allow_missing_config,
            )
        elif args.command == 'install-hooks':
            return install_hooks(args.config, store)
        elif args.command == 'migrate-config':
            return migrate_config(args.config)
        elif args.command == 'run':
            return run(args.config, store, args)
        elif args.command == 'sample-config':
            return sample_config()
        elif args.command == 'try-repo':
            return try_repo(args)
        elif args.command == 'uninstall':
            return uninstall(
                config_file=args.config,
                hook_types=args.hook_types,
            )
        elif args.command == 'validate-config':
            return validate_config(args.filenames)
        elif args.command == 'validate-manifest':
            return validate_manifest(args.filenames)
        else:
            raise NotImplementedError(
                f'Command {args.command} not implemented.',
            )

        raise AssertionError(
            f'Command {args.command} failed to exit with a returncode',
        )


if __name__ == '__main__':
    raise SystemExit(main())

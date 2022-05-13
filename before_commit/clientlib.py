from __future__ import annotations

import argparse
import functools
import logging
import os.path
import re
import shlex
import sys
from typing import Any
from typing import Sequence

from identify.identify import ALL_TAGS

import before_commit.constants as C
from before_commit.color import add_color_option
from before_commit.commands.validate_config import validate_config
from before_commit.commands.validate_manifest import validate_manifest
from before_commit.config import Array
from before_commit.config import check_and
from before_commit.config import check_any
from before_commit.config import check_array
from before_commit.config import check_bool
from before_commit.config import check_one_of
from before_commit.config import check_regex
from before_commit.config import check_string
from before_commit.config import check_type
from before_commit.config import Conditional
from before_commit.config import ConditionalOptional
from before_commit.config import ConditionalRecurse
from before_commit.config import load_from_filename
from before_commit.config import Map
from before_commit.config import NoAdditionalKeys
from before_commit.config import NotIn
from before_commit.config import Optional
from before_commit.config import OptionalNoDefault
from before_commit.config import OptionalRecurse
from before_commit.config import Required
from before_commit.config import RequiredRecurse
from before_commit.config import ValidationError
from before_commit.config import WarnAdditionalKeys
from before_commit.errors import FatalError
from before_commit.languages.all import all_languages
from before_commit.logging_handler import logging_handler
from before_commit.util import parse_version
from before_commit.util import yaml_load

logger = logging.getLogger('before_commit')

check_string_regex = check_and(check_string, check_regex)


def check_type_tag(tag: str) -> None:
    if tag not in ALL_TAGS:
        raise ValidationError(
            f'Type tag {tag!r} is not recognized.  '
            f'Try upgrading identify and pre-commit?',
        )


def check_min_version(version: str) -> None:
    if parse_version(version) > parse_version(C.VERSION):
        raise ValidationError(
            f'pre-commit version {version} is required but version '
            f'{C.VERSION} is installed.  '
            f'Perhaps run `pip install --upgrade pre-commit`.',
        )


def _make_argparser(filenames_help: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument('filenames', nargs='*', help=filenames_help)
    parser.add_argument('-V', '--version', action='version', version=C.VERSION)
    add_color_option(parser)
    return parser


MANIFEST_HOOK_DICT = Map(
    'Hook', 'id',

    Required('id', check_string),
    Required('name', check_string),
    Required('entry', check_string),
    Required('language', check_one_of(all_languages)),
    Optional('alias', check_string, ''),

    Optional('files', check_string_regex, ''),
    Optional('exclude', check_string_regex, '^$'),
    Optional('types', check_array(check_type_tag), ['file']),
    Optional('types_or', check_array(check_type_tag), []),
    Optional('exclude_types', check_array(check_type_tag), []),

    Optional(
        'additional_dependencies', check_array(check_string), [],
    ),
    Optional('args', check_array(check_string), []),
    Optional('always_run', check_bool, False),
    Optional('fail_fast', check_bool, False),
    Optional('pass_filenames', check_bool, True),
    Optional('description', check_string, ''),
    Optional('language_version', check_string, C.DEFAULT),
    Optional('log_file', check_string, ''),
    Optional('minimum_pre_commit_version', check_string, '0'),
    Optional('require_serial', check_bool, False),
    Optional('stages', check_array(check_one_of(C.STAGES)), []),
    Optional('verbose', check_bool, False),
)
MANIFEST_SCHEMA = Array(MANIFEST_HOOK_DICT)


class InvalidManifestError(FatalError):
    pass


load_manifest = functools.partial(
    load_from_filename,
    schema=MANIFEST_SCHEMA,
    load_strategy=yaml_load,
    exc_tp=InvalidManifestError,
)


def validate_manifest_main(argv: Sequence[str] | None = None) -> int:
    parser = _make_argparser('Manifest filenames.')
    args = parser.parse_args(argv)

    with logging_handler(args.color):
        logger.warning(
            'pre-commit-validate-manifest is deprecated -- '
            'use `pre-commit validate-manifest` instead.',
        )

        return validate_manifest(args.filenames)


LOCAL = 'local'
META = 'meta'


# should inherit from Conditional if sha support is dropped
class WarnMutableRev(ConditionalOptional):
    def check(self, dct: dict[str, Any]) -> None:
        super().check(dct)  # type: ignore

        if self.key in dct:
            rev = dct[self.key]

            if '.' not in rev and not re.match(r'^[a-fA-F0-9]+$', rev):
                logger.warning(
                    f'The {self.key!r} field of repo {dct["repo"]!r} '
                    f'appears to be a mutable reference '
                    f'(moving tag / branch).  Mutable references are never '
                    f'updated after first install and are not supported.  '
                    f'See https://pre-commit.com/#using-the-latest-version-for-a-repository '  # noqa: E501
                    f'for more details.  '
                    f'Hint: `pre-commit autoupdate` often fixes this.',
                )


class OptionalSensibleRegexAtHook(OptionalNoDefault):
    def check(self, dct: dict[str, Any]) -> None:
        super().check(dct)  # type: ignore

        if '/*' in dct.get(self.key, ''):
            logger.warning(
                f'The {self.key!r} field in hook {dct.get("id")!r} is a '
                f"regex, not a glob -- matching '/*' probably isn't what you "
                f'want here',
            )
        for fwd_slash_re in (r'[\\/]', r'[\/]', r'[/\\]'):
            if fwd_slash_re in dct.get(self.key, ''):
                logger.warning(
                    fr'pre-commit normalizes slashes in the {self.key!r} '
                    fr'field in hook {dct.get("id")!r} to forward slashes, '
                    fr'so you can use / instead of {fwd_slash_re}',
                )


class OptionalSensibleRegexAtTop(OptionalNoDefault):
    def check(self, dct: dict[str, Any]) -> None:
        super().check(dct)  # type: ignore

        if '/*' in dct.get(self.key, ''):
            logger.warning(
                f'The top-level {self.key!r} field is a regex, not a glob -- '
                f"matching '/*' probably isn't what you want here",
            )
        for fwd_slash_re in (r'[\\/]', r'[\/]', r'[/\\]'):
            if fwd_slash_re in dct.get(self.key, ''):
                logger.warning(
                    fr'pre-commit normalizes the slashes in the top-level '
                    fr'{self.key!r} field to forward slashes, so you '
                    fr'can use / instead of {fwd_slash_re}',
                )


class MigrateShaToRev:
    key = 'rev'

    @staticmethod
    def _cond(key: str) -> Conditional:
        return Conditional(
            key, check_string,
            condition_key='repo',
            condition_value=NotIn(LOCAL, META),
            ensure_absent=True,
        )

    def check(self, dct: dict[str, Any]) -> None:
        if dct.get('repo') in {LOCAL, META}:
            self._cond('rev').check(dct)  # type: ignore
            self._cond('sha').check(dct)  # type: ignore
        elif 'sha' in dct and 'rev' in dct:
            raise ValidationError('Cannot specify both sha and rev')
        elif 'sha' in dct:
            self._cond('sha').check(dct)  # type: ignore
        else:
            self._cond('rev').check(dct)  # type: ignore

    def apply_default(self, dct: dict[str, Any]) -> None:
        if 'sha' in dct:
            dct['rev'] = dct.pop('sha')

    remove_default = Required.remove_default  # type: ignore


def _entry(modname: str) -> str:
    """the hook `entry` is passed through `shlex.split()` by the command
    runner, so to prevent issues with spaces and backslashes (on Windows)
    it must be quoted here.
    """
    return f'{shlex.quote(sys.executable)} -m before_commit.meta_hooks.{modname}'  # noqa: E501


def warn_unknown_keys_root(
        extra: Sequence[str],
        orig_keys: Sequence[str],
        dct: dict[str, str],
) -> None:
    logger.warning(f'Unexpected key(s) present at root: {", ".join(extra)}')


def warn_unknown_keys_repo(
        extra: Sequence[str],
        orig_keys: Sequence[str],
        dct: dict[str, str],
) -> None:
    logger.warning(
        f'Unexpected key(s) present on {dct["repo"]}: {", ".join(extra)}',
    )


_meta = (
    (
        'check-hooks-apply', (
            ('name', 'Check hooks apply to the repository'),
            ('files', f'^{re.escape(C.DEFAULT_CONFIG_FILE)}$'),
            ('entry', _entry('check_hooks_apply')),
        ),
    ),
    (
        'check-useless-excludes', (
            ('name', 'Check for useless excludes'),
            ('files', f'^{re.escape(C.DEFAULT_CONFIG_FILE)}$'),
            ('entry', _entry('check_useless_excludes')),
        ),
    ),
    (
        'identity', (
            ('name', 'identity'),
            ('verbose', True),
            ('entry', _entry('identity')),
        ),
    ),
)


class NotAllowed(OptionalNoDefault):
    def check(self, dct: dict[str, Any]) -> None:
        if self.key in dct:
            raise ValidationError(f'{self.key!r} cannot be overridden')


META_HOOK_DICT = Map(
    'Hook', 'id',
    Required('id', check_string),
    Required('id', check_one_of(tuple(k for k, _ in _meta))),
    # language must be system
    Optional('language', check_one_of({'system'}), 'system'),
    # entry cannot be overridden
    NotAllowed('entry', check_any),
    *(
        # default to the hook definition for the meta hooks
        ConditionalOptional(key, check_any, value, 'id', hook_id, False)
        for hook_id, values in _meta
        for key, value in values
    ),
    *(
        # default to the "manifest" parsing
        OptionalNoDefault(item.key, item.check_fn)
        # these will always be defaulted above
        if item.key in {'name', 'language', 'entry'} else
        item
        for item in MANIFEST_HOOK_DICT.items
    ),
)
CONFIG_HOOK_DICT = Map(
    'Hook', 'id',

    Required('id', check_string),

    # All keys in manifest hook dict are valid in a config hook dict, but
    # are optional.
    # No defaults are provided here as the config is merged on top of the
    # manifest.
    *(
        OptionalNoDefault(item.key, item.check_fn)
        for item in MANIFEST_HOOK_DICT.items
        if item.key != 'id'
    ),
    OptionalSensibleRegexAtHook('files', check_string),
    OptionalSensibleRegexAtHook('exclude', check_string),
)
CONFIG_REPO_DICT = Map(
    'Repository', 'repo',

    Required('repo', check_string),

    ConditionalRecurse(
        'hooks', Array(CONFIG_HOOK_DICT),
        'repo', NotIn(LOCAL, META),
        False,
    ),
    ConditionalRecurse(
        'hooks', Array(MANIFEST_HOOK_DICT),
        'repo', LOCAL,
        False,
    ),
    ConditionalRecurse(
        'hooks', Array(META_HOOK_DICT),
        'repo', META,
        False,
    ),

    MigrateShaToRev(),
    WarnMutableRev(
        'rev',
        check_string,
        '',
        'repo',
        NotIn(LOCAL, META),
        True,
    ),
    WarnAdditionalKeys(('repo', 'rev', 'hooks'), warn_unknown_keys_repo),
)
DEFAULT_LANGUAGE_VERSION = Map(
    'DefaultLanguageVersion', None,
    NoAdditionalKeys(all_languages),
    *(Optional(x, check_string, C.DEFAULT) for x in all_languages),
)
CONFIG_SCHEMA = Map(
    'Config', None,

    RequiredRecurse('repos', Array(CONFIG_REPO_DICT)),
    Optional(
        'default_install_hook_types',
        check_array(check_one_of(C.HOOK_TYPES)),
        ['pre-commit'],
    ),
    OptionalRecurse(
        'default_language_version', DEFAULT_LANGUAGE_VERSION, {},
    ),
    Optional(
        'default_stages',
        check_array(check_one_of(C.STAGES)),
        C.STAGES,
    ),
    Optional('files', check_string_regex, ''),
    Optional('exclude', check_string_regex, '^$'),
    Optional('fail_fast', check_bool, False),
    Optional(
        'minimum_pre_commit_version',
        check_and(check_string, check_min_version),
        '0',
    ),
    WarnAdditionalKeys(
        (
            'repos',
            'default_install_hook_types',
            'default_language_version',
            'default_stages',
            'files',
            'exclude',
            'fail_fast',
            'minimum_pre_commit_version',
            'ci',
        ),
        warn_unknown_keys_root,
    ),
    OptionalSensibleRegexAtTop('files', check_string),
    OptionalSensibleRegexAtTop('exclude', check_string),

    # do not warn about configuration for pre-commit.ci
    OptionalNoDefault('ci', check_type(dict)),
)


class InvalidConfigError(FatalError):
    pass


def ordered_load_normalize_legacy_config(contents: str) -> dict[str, Any]:
    data = yaml_load(contents)
    if isinstance(data, list):
        logger.warning(
            'normalizing pre-commit configuration to a top-level map.  '
            'support for top level list will be removed in a future version.  '
            'run: `pre-commit migrate-config` to automatically fix this.',
        )
        return {'repos': data}
    else:
        return data


load_config = functools.partial(
    load_from_filename,
    schema=CONFIG_SCHEMA,
    load_strategy=ordered_load_normalize_legacy_config,
    exc_tp=InvalidConfigError,
)


def validate_config_main(argv: Sequence[str] | None = None) -> int:
    parser = _make_argparser('Config filenames.')
    args = parser.parse_args(argv)

    with logging_handler(args.color):
        logger.warning(
            'pre-commit-validate-config is deprecated -- '
            'use `pre-commit validate-config` instead.',
        )

        return validate_config(args.filenames)


def detect_manifest_file(path: str) -> str:
    default_ret = os.path.join(path, C.DEFAULT_MANIFEST_FILE)
    ret = default_ret

    found = 0
    for file in C.MANIFEST_FILES:
        file_path = os.path.join(path, file)
        if os.path.exists(file_path):
            ret = file_path
            found += 1
            if found == 1:
                default_ret = file_path
            if found > 1:
                logger.warning('Duplicate manifest file \'%s\'', file)
    if found > 1:
        logger.warning('Fallback to \'%s\'', os.path.basename(default_ret))
        ret = default_ret

    return ret

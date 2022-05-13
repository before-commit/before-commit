from __future__ import annotations

import sys

if sys.version_info >= (3, 8):  # pragma: >=3.8 cover
    import importlib.metadata as importlib_metadata
else:  # pragma: <3.8 cover
    import importlib_metadata

DEFAULT_CONFIG_FILE = '.pre-commit-config.yaml'
CONFIG_FILES = [
    '.pre-commit-config.yaml',
    '.pre-commit-config.yml',
]
DEFAULT_MANIFEST_FILE = '.pre-commit-hooks.yaml'
MANIFEST_FILES = [
    '.pre-commit-hooks.yaml',
    '.pre-commit-hooks.yml',
]

# Bump when installation changes in a backwards / forwards incompatible way
INSTALLED_STATE_VERSION = '1'
# Bump when modifying `empty_template`
LOCAL_REPO_VERSION = '1'

VERSION = importlib_metadata.version('before_commit')

# `manual` is not invoked by any installed git hook.  See #719
STAGES = (
    'commit', 'merge-commit', 'prepare-commit-msg', 'commit-msg',
    'post-commit', 'manual', 'post-checkout', 'push', 'post-merge',
    'post-rewrite',
)

HOOK_TYPES = (
    'pre-commit', 'pre-merge-commit', 'pre-push', 'prepare-commit-msg',
    'commit-msg', 'post-commit', 'post-checkout', 'post-merge',
    'post-rewrite',
)

DEFAULT = 'default'

from __future__ import annotations

from typing import Callable
from typing import Sequence

from before_commit.hook import Hook
from before_commit.languages import helpers
from before_commit.languages.docker import docker_cmd
from before_commit.prefix import Prefix

ENVIRONMENT_DIR: str | None = None
get_default_version: Callable[[], str] = helpers.basic_get_default_version
health_check: Callable[[Prefix, str], str | None] = \
    helpers.basic_health_check
install_environment: Callable[[Prefix, str, Sequence[str]], None] = \
    helpers.no_install


def run_hook(
        hook: Hook,
        file_args: Sequence[str],
        color: bool,
) -> tuple[int, bytes]:  # pragma: win32 no cover # pragma: darwin no cover
    cmd = docker_cmd() + hook.cmd
    return helpers.run_xargs(hook, cmd, file_args, color=color)

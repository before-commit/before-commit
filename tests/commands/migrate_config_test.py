from __future__ import annotations

import before_commit.constants as C
from before_commit.commands.migrate_config import migrate_config


def test_migrate_config_normal_format(tmpdir, capsys):
    cfg = tmpdir.join(C.DEFAULT_CONFIG_FILE)
    cfg.write(
        '-   repo: local\n'
        '    hooks:\n'
        '    -   id: foo\n'
        '        name: foo\n'
        '        entry: ./bin/foo.sh\n'
        '        language: script\n',
    )
    with tmpdir.as_cwd():
        assert not migrate_config(C.DEFAULT_CONFIG_FILE)
    out, _ = capsys.readouterr()
    assert out == 'Configuration has been migrated.\n'
    contents = cfg.read()
    assert contents == (
        'repos:\n'
        '-   repo: local\n'
        '    hooks:\n'
        '    -   id: foo\n'
        '        name: foo\n'
        '        entry: ./bin/foo.sh\n'
        '        language: script\n'
    )


def test_migrate_config_document_marker(tmpdir):
    cfg = tmpdir.join(C.DEFAULT_CONFIG_FILE)
    cfg.write(
        '# comment\n'
        '\n'
        '---\n'
        '-   repo: local\n'
        '    hooks:\n'
        '    -   id: foo\n'
        '        name: foo\n'
        '        entry: ./bin/foo.sh\n'
        '        language: script\n',
    )
    with tmpdir.as_cwd():
        assert not migrate_config(C.DEFAULT_CONFIG_FILE)
    contents = cfg.read()
    assert contents == (
        '# comment\n'
        '\n'
        '---\n'
        'repos:\n'
        '-   repo: local\n'
        '    hooks:\n'
        '    -   id: foo\n'
        '        name: foo\n'
        '        entry: ./bin/foo.sh\n'
        '        language: script\n'
    )


def test_migrate_config_list_literal(tmpdir):
    cfg = tmpdir.join(C.DEFAULT_CONFIG_FILE)
    cfg.write(
        '[{\n'
        '    repo: local,\n'
        '    hooks: [{\n'
        '        id: foo, name: foo, entry: ./bin/foo.sh,\n'
        '        language: script,\n'
        '    }]\n'
        '}]',
    )
    with tmpdir.as_cwd():
        assert not migrate_config(C.DEFAULT_CONFIG_FILE)
    contents = cfg.read()
    assert contents == (
        'repos:\n'
        '    [{\n'
        '        repo: local,\n'
        '        hooks: [{\n'
        '            id: foo, name: foo, entry: ./bin/foo.sh,\n'
        '            language: script,\n'
        '        }]\n'
        '    }]'
    )


def test_already_migrated_configuration_noop(tmpdir, capsys):
    contents = (
        'repos:\n'
        '-   repo: local\n'
        '    hooks:\n'
        '    -   id: foo\n'
        '        name: foo\n'
        '        entry: ./bin/foo.sh\n'
        '        language: script\n'
    )
    cfg = tmpdir.join(C.DEFAULT_CONFIG_FILE)
    cfg.write(contents)
    with tmpdir.as_cwd():
        assert not migrate_config(C.DEFAULT_CONFIG_FILE)
    out, _ = capsys.readouterr()
    assert out == 'Configuration is already migrated.\n'
    assert cfg.read() == contents


def test_migrate_config_sha_to_rev(tmpdir):
    contents = (
        'repos:\n'
        '-   repo: https://github.com/pre-commit/pre-commit-hooks\n'
        '    sha: v1.2.0\n'
        '    hooks: []\n'
        '-   repo: https://github.com/pre-commit/pre-commit-hooks\n'
        '    sha: v1.2.0\n'
        '    hooks: []\n'
    )
    cfg = tmpdir.join(C.DEFAULT_CONFIG_FILE)
    cfg.write(contents)
    with tmpdir.as_cwd():
        assert not migrate_config(C.DEFAULT_CONFIG_FILE)
    contents = cfg.read()
    assert contents == (
        'repos:\n'
        '-   repo: https://github.com/pre-commit/pre-commit-hooks\n'
        '    rev: v1.2.0\n'
        '    hooks: []\n'
        '-   repo: https://github.com/pre-commit/pre-commit-hooks\n'
        '    rev: v1.2.0\n'
        '    hooks: []\n'
    )

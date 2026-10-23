#!/usr/bin/env python3
"""Test-path discovery shared by planning and grounding without consumer execution."""
from __future__ import annotations

import configparser
import fnmatch
import subprocess
import tomllib
from collections.abc import Callable
from pathlib import Path

TEST_DIR_MARKERS = {'test', 'tests', '__tests__', 'spec', 'specs', 'fixtures', 'e2e', 'cypress'}
TEST_FILE_SUFFIXES = (
    '.feature', '.robot', '.bats', '.test.json', '.spec.json',
    '.cy.ts', '.cy.tsx', '.cy.js', '.cy.jsx',
    '.e2e.ts', '.e2e.tsx', '.e2e.js', '.e2e.jsx',
)
TEST_RUNNER_CONFIGS = ('pytest.ini', 'tox.ini', 'conftest.py')
TEST_RUNNER_MANIFESTS = {'package.json', 'pyproject.toml'}
TEST_RUNNER_CONFIG_PREFIXES = ('jest.config.', 'vitest.config.', 'playwright.config.', 'cypress.config.')


def pytest_patterns_from_config(path: str, contents: str) -> tuple[str, ...]:
    """Read declared pytest file globs without executing project configuration."""
    name = Path(path).name.lower()
    if name == 'pyproject.toml':
        data = tomllib.loads(contents)
        options = data.get('tool', {}).get('pytest', {}).get('ini_options', {})
    elif name in {'pytest.ini', 'tox.ini', 'setup.cfg'}:
        parser = configparser.ConfigParser(interpolation=None)
        parser.read_string(contents)
        section = 'tool:pytest' if name == 'setup.cfg' else 'pytest'
        options = parser[section] if parser.has_section(section) else {}
    else:
        return ()
    raw = options.get('python_files') if isinstance(options, dict) else options.get('python_files', fallback=None)
    if raw is None:
        return ()
    patterns = raw.split() if isinstance(raw, str) else raw
    if not isinstance(patterns, (list, tuple)) or any(not isinstance(item, str) for item in patterns):
        raise ValueError(f'invalid pytest python_files in {path}')
    return tuple(pattern.strip() for pattern in patterns if pattern.strip())


def pytest_discovery_configs(
    paths: list[str], read_source: Callable[[str], str | None],
) -> dict[str, tuple[str, ...]]:
    """Discover runner settings only in affected paths' ancestor directories."""
    config_paths: set[str] = set()
    for path in paths:
        parents = Path(path.replace('\\', '/')).parts[:-1]
        for depth in range(len(parents) + 1):
            prefix = '/'.join(parents[:depth])
            for name in ('pytest.ini', 'pyproject.toml', 'tox.ini', 'setup.cfg'):
                config_paths.add(f'{prefix}/{name}' if prefix else name)
    discovered: dict[str, tuple[str, ...]] = {}
    for config_path in sorted(config_paths):
        source = read_source(config_path)
        if source is not None:
            patterns = pytest_patterns_from_config(config_path, source)
            if patterns:
                discovered[config_path] = patterns
    return discovered


def matches_pytest_discovery(path: str, configs: dict[str, tuple[str, ...]]) -> bool:
    normalized = path.replace('\\', '/').lower()
    for config_path, patterns in configs.items():
        root = config_path.rpartition('/')[0].lower()
        if root and not normalized.startswith(root + '/'):
            continue
        relative = normalized[len(root) + 1:] if root else normalized
        for pattern in patterns:
            match_pattern = pattern.lower()
            target = relative if '/' in match_pattern else relative.rsplit('/', 1)[-1]
            if fnmatch.fnmatchcase(target, match_pattern):
                return True
    return False


def is_test_path(path: str, *, pytest_configs: dict[str, tuple[str, ...]] | None = None) -> bool:
    parts = [part for part in path.replace('\\', '/').lower().split('/') if part]
    name = parts[-1] if parts else ''
    return (
        any(part in TEST_DIR_MARKERS for part in parts[:-1])
        or (bool(pytest_configs) and matches_pytest_discovery(path, pytest_configs))
        or name.startswith('test_')
        or '.test.' in name
        or '.spec.' in name
        or name.endswith(('_test.py', '_test.go'))
        or name.endswith(TEST_FILE_SUFFIXES)
        or name in TEST_RUNNER_CONFIGS
        or name in TEST_RUNNER_MANIFESTS
        or name.startswith(TEST_RUNNER_CONFIG_PREFIXES)
    )


def git_revision_file(repo_path: Path, head_sha: object, config_path: str) -> str | None:
    if not repo_path.is_dir() or not isinstance(head_sha, str):
        return None
    result = subprocess.run(
        ["git", "-C", str(repo_path), "show", f"{head_sha}:{config_path}"],
        capture_output=True, text=True, check=False,
    )
    return result.stdout if result.returncode == 0 else None


def pytest_discovery_configs_from_git(
    paths: list[str], repo: Path, head_sha: object,
) -> dict[str, tuple[str, ...]]:
    try:
        return pytest_discovery_configs(
            paths, lambda config_path: git_revision_file(repo, head_sha, config_path),
        )
    except (ValueError, configparser.Error, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"runner discovery cannot be trusted: {exc}") from exc

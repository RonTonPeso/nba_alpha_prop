"""Repo-root resolution and dotenv load-once behavior."""

from __future__ import annotations

from pathlib import Path

import app.paths as paths


def test_find_repo_root_monorepo() -> None:
    root = paths.find_repo_root()
    assert (root / "docs").is_dir()
    assert (root / "backend" / "pyproject.toml").is_file()


def test_find_repo_root_docker_layout(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "db").mkdir()
    fake = tmp_path / "app" / "db" / "engine.py"
    fake.write_text("# fake\n")
    assert paths.find_repo_root(fake) == tmp_path.resolve()


def test_load_repo_dotenv_once(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("NBA_LOAD_DOTENV", "0")
    paths._DOTENV_LOADED = False
    paths.load_repo_dotenv()
    assert paths._DOTENV_LOADED is True
    # Second call is a no-op even if the flag would allow loading.
    monkeypatch.setenv("NBA_LOAD_DOTENV", "1")
    paths.load_repo_dotenv()
    assert paths._DOTENV_LOADED is True

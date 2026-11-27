"""Resolve the repo (or Docker app) root without brittle parents[N]."""

from __future__ import annotations

import os
from pathlib import Path

_DOTENV_LOADED = False


def find_repo_root(start: Path | None = None) -> Path:
    """Return the monorepo root, or the Docker ``/app`` layout root.

    Prefer monorepo markers (``docs/`` plus ``backend/pyproject.toml`` or
    ``models/``) so a walk from ``backend/app/...`` does not stop at
    ``backend/`` (which also has ``pyproject.toml`` + ``app/``). Fall back
    to the image layout from ``backend/Dockerfile`` (WORKDIR with
    ``pyproject.toml`` beside ``app/``).
    """
    here = (start or Path(__file__)).resolve()
    if here.is_file():
        here = here.parent
    candidates = [here, *here.parents]
    for candidate in candidates:
        has_docs = (candidate / "docs").is_dir()
        has_backend_project = (candidate / "backend" / "pyproject.toml").is_file()
        has_models = (candidate / "models").is_dir()
        if has_docs and (has_backend_project or has_models):
            return candidate
    for candidate in candidates:
        if (candidate / "pyproject.toml").is_file() and (candidate / "app").is_dir():
            return candidate
    raise RuntimeError(f"could not find repo root from {here}")


def load_repo_dotenv() -> None:
    """Load repo-root ``.env`` once; never override existing process env.

    Set ``NBA_LOAD_DOTENV=0`` to skip (CI / containers). A later re-import
    does not call ``load_dotenv`` again, so an ``unset ANTHROPIC_API_KEY``
    in the same process is not resurrected by this module.
    """
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    _DOTENV_LOADED = True
    flag = os.environ.get("NBA_LOAD_DOTENV", "1").strip().lower()
    if flag in {"0", "false", "no", "off"}:
        return
    env_path = find_repo_root() / ".env"
    if not env_path.is_file():
        return
    from dotenv import load_dotenv

    load_dotenv(env_path, override=False)

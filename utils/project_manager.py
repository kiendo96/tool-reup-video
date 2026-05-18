"""Project workspace helpers.

Each project is a self-contained workspace under workspace/projects/<slug>/.
This keeps uploads, audio, transcripts, TTS, outputs and cache separated.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import List

PROJECTS_ROOT = Path("workspace") / "projects"
PROJECT_SUBDIRS = ["uploads", "audios", "transcripts", "tts_audios", "outputs"]


def slugify_project_name(name: str) -> str:
    slug = (name or "").strip().lower()
    slug = re.sub(r"[^a-z0-9\-_\s]+", "", slug)
    slug = re.sub(r"\s+", "-", slug).strip("-_")
    return slug or "default"


def ensure_projects_root() -> Path:
    PROJECTS_ROOT.mkdir(parents=True, exist_ok=True)
    return PROJECTS_ROOT


def list_projects() -> List[str]:
    root = ensure_projects_root()
    return sorted([p.name for p in root.iterdir() if p.is_dir()])


def ensure_project(project_name: str) -> Path:
    root = ensure_projects_root()
    slug = slugify_project_name(project_name)
    project_dir = root / slug
    project_dir.mkdir(parents=True, exist_ok=True)
    for subdir in PROJECT_SUBDIRS:
        (project_dir / subdir).mkdir(parents=True, exist_ok=True)
    return project_dir


def import_project_folder(source_path: str, project_name: str, overwrite: bool = False) -> Path:
    """Copy an existing workspace/project folder into workspace/projects/<name>.

    This is intentionally copy-only; it never deletes or moves the original folder.
    """
    source = Path(source_path).expanduser()
    if not source.exists() or not source.is_dir():
        raise FileNotFoundError(f"Không tìm thấy folder project cũ: {source_path}")

    dest = ensure_projects_root() / slugify_project_name(project_name or source.name)
    if dest.exists() and any(dest.iterdir()):
        if not overwrite:
            raise FileExistsError(f"Project đã tồn tại: {dest.name}")
        shutil.rmtree(dest)

    shutil.copytree(source, dest, dirs_exist_ok=True)
    for subdir in PROJECT_SUBDIRS:
        (dest / subdir).mkdir(parents=True, exist_ok=True)
    return dest

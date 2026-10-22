"""Safe session paths and atomic JSON writes."""

import json
import os
import tempfile
from pathlib import Path
from uuid import UUID


def session_directory(base: Path, session_id: str, *, allow_default: bool = False) -> Path:
    try:
        valid = (allow_default and session_id == "default") or str(UUID(session_id)) == session_id
    except (ValueError, TypeError, AttributeError):
        valid = False
    if not valid:
        raise ValueError("Invalid session ID.")
    root = base.resolve()
    candidate = root / session_id
    if candidate.is_symlink() or candidate.resolve().parent != root:
        raise ValueError("Invalid session directory.")
    return candidate


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         delete=False) as handle:
            temporary = handle.name
            json.dump(value, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)

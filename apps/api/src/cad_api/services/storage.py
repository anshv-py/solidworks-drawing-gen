"""Root-confined file storage with server-generated names."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path
from typing import BinaryIO

from cad_api.errors import ApiError, FileTooLarge

CHUNK = 1 << 20


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


class Storage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def path(self, *parts: str) -> Path:
        """Join under the root; refuses anything that escapes it (path traversal)."""
        p = self.root.joinpath(*parts).resolve()
        if not p.is_relative_to(self.root):
            raise ApiError("invalid storage path", code="INVALID_PATH", status=400)
        return p

    def model_dir(self, model_id: str) -> Path:
        d = self.path("models", model_id)
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
        return d

    def job_dir(self, job_id: str) -> Path:
        d = self.path("jobs", job_id)
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
        return d

    def drawing_dir(self, job_id: str) -> Path:
        d = self.path("drawings", job_id)
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
        return d

    def receive(self, src: BinaryIO, limit: int) -> Path:
        """Stream an upload into a private temp file under the root, enforcing the size limit."""
        tmp_dir = self.path("tmp")
        tmp_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, name = tempfile.mkstemp(dir=tmp_dir, prefix="upload-")
        total = 0
        try:
            with os.fdopen(fd, "wb") as out:
                while chunk := src.read(CHUNK):
                    total += len(chunk)
                    if total > limit:
                        raise FileTooLarge(f"file exceeds the {limit // (1024 * 1024)} MB limit")
                    out.write(chunk)
        except BaseException:
            Path(name).unlink(missing_ok=True)
            raise
        return Path(name)

    def commit_upload(self, tmp: Path, model_id: str, ext: str) -> Path:
        dest = self.model_dir(model_id) / f"source{ext}"
        shutil.move(tmp, dest)
        os.chmod(dest, 0o400)
        return dest

    def model_source(self, model_id: str, fmt: str) -> Path:
        return self.path("models", model_id, "source.step" if fmt == "STEP" else "source.stl")

    def remove_job_dir(self, job_id: str) -> None:
        shutil.rmtree(self.path("jobs", job_id), ignore_errors=True)

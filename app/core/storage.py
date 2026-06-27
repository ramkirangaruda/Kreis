"""Local file storage (Phase 1).

Phase 3 will swap this for MinIO/S3; keep the public API (`save_upload`)
stable so callers don't change.
"""

import os
import shutil
import uuid

from fastapi import UploadFile

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


async def save_upload(file: UploadFile, subfolder: str) -> str:
    folder = os.path.join(UPLOAD_DIR, subfolder)
    os.makedirs(folder, exist_ok=True)

    name = file.filename or "file"
    ext = name.rsplit(".", 1)[-1] if "." in name else "bin"
    filename = f"{uuid.uuid4()}.{ext}"
    path = os.path.join(folder, filename)

    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    return f"/uploads/{subfolder}/{filename}"

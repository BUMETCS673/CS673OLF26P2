"""Uploaded study materials.

    POST /api/materials (multipart, with a `file` field)
      -> 202 Document   processing started
      -> 200 Document   this user already has this file, so nothing to process
      -> 400 too large, 422 + field, 429 rate_limited

    GET /api/materials/<id>
      -> 200 Document   the upload screen polls this for progress
      -> 404            also for another user's document
"""

import os
import tempfile
from pathlib import Path

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from app.ai.reading import PDF
from app.errors import not_found, validation_error
from app.models import Document
from app.services.materials import accept_upload, fail_if_stale

materials_bp = Blueprint("materials", __name__)

FILE_MAX = 50 * 1024 * 1024
BODY_MAX = FILE_MAX + 1024 * 1024  # room for the multipart wrapping. This route only.
FILE_NAME_MAX = 255

# By extension, because browsers disagree on the type of a Markdown file. _check_content() and
# the reader both look at the real content afterward.
TYPES_BY_EXTENSION = {".pdf": PDF, ".txt": "text/plain", ".md": "text/markdown"}
UNSUPPORTED_FILE = "Only PDF, TXT and MD files are supported. Save other documents as a PDF first."


def _check_content(path: str, mime_type: str) -> None:
    size = os.path.getsize(path)
    if size == 0:
        raise validation_error("That file is empty.", "file")
    if size > FILE_MAX:
        raise validation_error("The file must be 50 MB or smaller.", "file")
    if mime_type == PDF:
        with open(path, "rb") as file:
            if file.read(5) != b"%PDF-":
                raise validation_error("That file isn't a valid PDF.", "file")


@materials_bp.post("/materials")
@login_required
def upload_material():
    # Before anything reads the body.
    request.max_content_length = BODY_MAX

    file = request.files.get("file")
    if file is None or not file.filename:
        raise validation_error("file is required.", "file")
    if len(file.filename) > FILE_NAME_MAX:
        raise validation_error(
            f"The file name must be at most {FILE_NAME_MAX} characters.", "file"
        )
    mime_type = TYPES_BY_EXTENSION.get(Path(file.filename).suffix.lower())
    if mime_type is None:
        raise validation_error(UNSUPPORTED_FILE, "file")

    # From here accept_upload() owns the temp file, unless the content check fails first. The name
    # is ours: the browser's is only stored and displayed, never used as a path.
    handle, path = tempfile.mkstemp(prefix="cadence-upload-")
    os.close(handle)
    try:
        file.save(path)
        _check_content(path, mime_type)
    except Exception:
        Path(path).unlink(missing_ok=True)
        raise

    document, started = accept_upload(current_user.id, file.filename, path, mime_type)
    return jsonify(document.to_dict()), 202 if started else 200


@materials_bp.get("/materials/<int:document_id>")
@login_required
def get_material(document_id):
    document = Document.query.filter_by(id=document_id, user_id=current_user.id).first()
    if document is None:
        raise not_found("Document not found")
    fail_if_stale(document)
    return jsonify(document.to_dict())

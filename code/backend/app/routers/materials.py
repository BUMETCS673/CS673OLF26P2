"""Uploaded study files. Someone else's file answers 404, never 403."""

from collections.abc import AsyncGenerator

from fastapi import APIRouter, Request, Response, status
from starlette.datastructures import FormData, UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from app.core.database import SessionDep
from app.core.errors import InvalidRequest
from app.dependencies import CurrentUser, MaterialServiceDep
from app.schemas.materials import MaterialRead
from app.services.materials import FILE_MAX, FILE_TOO_LARGE

router = APIRouter(prefix="/api/materials", tags=["materials"])

BODY_MAX = FILE_MAX + 1024 * 1024  # room for the multipart wrapping
FILE_REQUIRED = "file is required."


async def _limited_body(request: Request) -> AsyncGenerator[bytes, None]:
    """The body as it arrives, stopping at the limit. A client's stated length can be false."""
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > BODY_MAX:
            raise InvalidRequest(FILE_TOO_LARGE, "file")
        yield chunk


async def _parse_form(request: Request) -> FormData:
    """Parsed here, rather than by FastAPI, to enforce the limit while the body is still arriving.

    The file is spooled to a temporary file, so its size doesn't matter to memory.
    """
    if not request.headers.get("content-type", "").startswith("multipart/form-data"):
        raise InvalidRequest(FILE_REQUIRED, "file")
    parser = MultiPartParser(request.headers, _limited_body(request), max_files=1, max_fields=1)
    try:
        return await parser.parse()
    except MultiPartException:
        raise InvalidRequest(FILE_REQUIRED, "file") from None


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def upload_material(
    request: Request,
    response: Response,
    user: CurrentUser,
    session: SessionDep,
    service: MaterialServiceDep,
) -> MaterialRead:
    """202 if indexing started, or 200 if this user already has this file."""
    # A slow upload can take minutes, and mustn't hold a database connection meanwhile.
    user_id = user.id
    await session.close()

    form = await _parse_form(request)
    try:
        file = form.get("file")
        if not isinstance(file, UploadFile) or not file.filename:
            raise InvalidRequest(FILE_REQUIRED, "file")
        material, started = await service.upload(user_id, file.filename, file)
    finally:
        await form.close()

    if not started:
        response.status_code = status.HTTP_200_OK
    return material


@router.get("/{document_id}")
async def get_material(
    document_id: int, user: CurrentUser, service: MaterialServiceDep
) -> MaterialRead:
    return await service.get(document_id, user.id)

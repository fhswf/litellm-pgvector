"""OpenAI-compatible Files and vector-store file attachment endpoints."""

from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Query
from sqlalchemy import text, tuple_
from sqlalchemy.exc import OperationalError
from sqlmodel import select

from classes.database import File, VectorStore, VectorStoreFile, database_instance
from classes.ingestion import DEFAULT_CHUNKING_STRATEGY, refresh_store_usage
from classes.s3_file_handler import S3FileHandler
from config import settings
from models import (
    DeleteFileResponse,
    UploadFileRequest,
    UploadFileResponse,
    VectorStoreFileDeletedResponse,
    VectorStoreFileListResponse,
    VectorStoreFileRequest,
    VectorStoreFileResponse,
)
from util import get_litellm_user_id, get_litellm_vkey_info, is_litellm_admin, scope_to_litellm_user


router = APIRouter()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _s3_handler() -> S3FileHandler:
    return S3FileHandler(
        region=settings.s3_region,
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key,
        bucket=settings.s3_bucket,
        host=settings.s3_host,
    )


def _file_response(file: File) -> UploadFileResponse:
    return UploadFileResponse(
        id=file.id.hex,
        bytes=file.size,
        created_at=int(file.created_at.timestamp()),
        filename=file.filename,
        purpose=file.purpose,
        expires_at=int(file.expires_at.timestamp()) if file.expires_at else None,
    )


def _attachment_response(attachment: VectorStoreFile) -> VectorStoreFileResponse:
    return VectorStoreFileResponse(
        id=attachment.file_id.hex,
        created_at=int(attachment.created_at.timestamp()),
        last_error=attachment.last_error,
        status=attachment.status,
        usage_bytes=attachment.usage_bytes,
        vector_store_id=attachment.vector_store_id.hex,
        attributes=attachment.attributes,
        chunking_strategy=attachment.chunking_strategy_config or {"type": "other"},
    )


def _store(session, store_id: UUID, key_info: dict) -> VectorStore:
    statement = scope_to_litellm_user(
        select(VectorStore).where(VectorStore.id == store_id), VectorStore, key_info
    )
    store = session.exec(statement).first()
    if store is None:
        raise HTTPException(status_code=404, detail="Vector store not found")
    return store


def _attachment(session, store_id: UUID, file_id: UUID) -> VectorStoreFile:
    attachment = session.exec(
        select(VectorStoreFile).where(
            VectorStoreFile.vector_store_id == store_id,
            VectorStoreFile.file_id == file_id,
        )
    ).first()
    if attachment is None:
        raise HTTPException(status_code=404, detail="Vector store file not found")
    return attachment


@router.post("/files", response_model=UploadFileResponse, include_in_schema=False)
@router.post("/v1/files", response_model=UploadFileResponse)
async def upload_file(
    data: Annotated[UploadFileRequest, Form()],
    litellm_vkey_info=Depends(get_litellm_vkey_info),
):
    if is_litellm_admin(litellm_vkey_info):
        raise HTTPException(status_code=400, detail="Upload with a LiteLLM user key")
    if not data.file.filename:
        raise HTTPException(status_code=400, detail="A filename is required")

    user_id = get_litellm_user_id(litellm_vkey_info)
    upload = await _s3_handler().upload_file(data.file, f"user/{user_id}")
    created_at = _utc_now()
    with database_instance.session() as session:
        file = File(
            user_id=user_id,
            team_id=None,
            filename=data.file.filename,
            size=upload["bytes"],
            purpose=data.purpose,
            created_at=created_at,
            expires_at=(
                created_at + timedelta(seconds=data.expires_after.seconds)
                if data.expires_after else None
            ),
            filename_on_disk=upload["s3_key"],
        )
        session.add(file)
        try:
            session.commit()
        except Exception:
            session.rollback()
            await _s3_handler().delete_file(upload["s3_key"])
            raise
        return _file_response(file)


@router.get("/v1/files/{file_id}", response_model=UploadFileResponse)
async def retrieve_file(file_id: UUID, litellm_vkey_info=Depends(get_litellm_vkey_info)):
    with database_instance.session() as session:
        statement = scope_to_litellm_user(
            select(File).where(File.id == file_id), File, litellm_vkey_info
        )
        file = session.exec(statement).first()
        if file is None:
            raise HTTPException(status_code=404, detail="File not found")
        return _file_response(file)


@router.delete("/v1/files/{file_id}", response_model=DeleteFileResponse)
async def delete_file(file_id: UUID, litellm_vkey_info=Depends(get_litellm_vkey_info)):
    with database_instance.session() as session:
        statement = scope_to_litellm_user(
            select(File).where(File.id == file_id), File, litellm_vkey_info
        )
        file = session.exec(statement).first()
        if file is None:
            raise HTTPException(status_code=404, detail="File not found")
        storage_key = file.filename_on_disk
        store_ids = {attachment.vector_store_id for attachment in file.vector_store_files}
        session.delete(file)
        session.flush()
        for store_id in store_ids:
            refresh_store_usage(session, store_id)
        session.commit()
    await _s3_handler().delete_file(storage_key)
    return DeleteFileResponse(id=file_id.hex)


@router.post(
    "/v1/vector_stores/{vector_store_id}/files",
    response_model=VectorStoreFileResponse,
)
def create_vector_store_file(
    vector_store_id: UUID,
    request: VectorStoreFileRequest,
    litellm_vkey_info=Depends(get_litellm_vkey_info),
):
    try:
        file_id = UUID(request.file_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid file ID") from exc

    try:
        with database_instance.session() as session:
            # A stalled transaction must not hold the request indefinitely.
            session.exec(text("SET LOCAL lock_timeout = '2s'"))
            store = _store(session, vector_store_id, litellm_vkey_info)
            # Lock the store row so two concurrent requests cannot create the same
            # attachment before either transaction commits.
            session.exec(select(VectorStore).where(VectorStore.id == store.id).with_for_update()).first()
            statement = scope_to_litellm_user(
                select(File).where(File.id == file_id), File, litellm_vkey_info
            )
            file = session.exec(statement).first()
            if file is None or file.user_id != store.user_id:
                raise HTTPException(status_code=404, detail="File not found")
            existing = session.exec(
                select(VectorStoreFile).where(
                    VectorStoreFile.vector_store_id == store.id,
                    VectorStoreFile.file_id == file_id,
                )
            ).first()
            if existing is not None:
                raise HTTPException(status_code=400, detail="File is already attached to this vector store")

            strategy = request.chunking_strategy
            effective_strategy = (
                strategy.model_dump() if strategy and strategy.type == "static"
                else DEFAULT_CHUNKING_STRATEGY.copy()
            )
            attachment = VectorStoreFile(
                file_id=file_id,
                user_id=store.user_id,
                team_id=store.team_id,
                vector_store_id=store.id,
                attributes=request.attributes,
                chunking_strategy="static",
                chunking_strategy_config=effective_strategy,
                usage_bytes=0,
                status="in_progress",
                created_at=_utc_now(),
            )
            session.add(attachment)
            session.flush()
            refresh_store_usage(session, store.id)
            session.commit()
            return _attachment_response(attachment)
    except OperationalError as exc:
        if getattr(exc.orig, "pgcode", None) == "55P03":
            raise HTTPException(
                status_code=503,
                detail="Vector store is busy; retry shortly",
                headers={"Retry-After": "2"},
            ) from exc
        raise


@router.get(
    "/v1/vector_stores/{vector_store_id}/files/{file_id}",
    response_model=VectorStoreFileResponse,
)
async def retrieve_vector_store_file(
    vector_store_id: UUID,
    file_id: UUID,
    litellm_vkey_info=Depends(get_litellm_vkey_info),
):
    with database_instance.session() as session:
        _store(session, vector_store_id, litellm_vkey_info)
        return _attachment_response(_attachment(session, vector_store_id, file_id))


@router.get(
    "/v1/vector_stores/{vector_store_id}/files",
    response_model=VectorStoreFileListResponse,
)
async def list_vector_store_files(
    vector_store_id: UUID,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    order: Literal["asc", "desc"] = "desc",
    after: UUID | None = None,
    before: UUID | None = None,
    filter: Literal["in_progress", "completed", "failed", "cancelled"] | None = None,
    litellm_vkey_info=Depends(get_litellm_vkey_info),
):
    with database_instance.session() as session:
        _store(session, vector_store_id, litellm_vkey_info)
        statement = select(VectorStoreFile).where(VectorStoreFile.vector_store_id == vector_store_id)
        if filter:
            statement = statement.where(VectorStoreFile.status == filter)
        for cursor_id, direction in ((after, "after"), (before, "before")):
            if cursor_id is None:
                continue
            cursor = _attachment(session, vector_store_id, cursor_id)
            position = tuple_(VectorStoreFile.created_at, VectorStoreFile.id)
            cursor_position = (cursor.created_at, cursor.id)
            if (direction == "after") == (order == "asc"):
                statement = statement.where(position > cursor_position)
            else:
                statement = statement.where(position < cursor_position)
        columns = (VectorStoreFile.created_at, VectorStoreFile.id)
        statement = statement.order_by(*(
            column.asc() if order == "asc" else column.desc() for column in columns
        )).limit(limit + 1)
        rows = session.exec(statement).all()
        has_more = len(rows) > limit
        data = [_attachment_response(row) for row in rows[:limit]]
        return VectorStoreFileListResponse(
            data=data,
            first_id=data[0].id if data else None,
            last_id=data[-1].id if data else None,
            has_more=has_more,
        )


@router.delete(
    "/v1/vector_stores/{vector_store_id}/files/{file_id}",
    response_model=VectorStoreFileDeletedResponse,
)
async def delete_vector_store_file(
    vector_store_id: UUID,
    file_id: UUID,
    litellm_vkey_info=Depends(get_litellm_vkey_info),
):
    with database_instance.session() as session:
        _store(session, vector_store_id, litellm_vkey_info)
        attachment = _attachment(session, vector_store_id, file_id)
        session.delete(attachment)
        session.flush()
        refresh_store_usage(session, vector_store_id)
        session.commit()
    return VectorStoreFileDeletedResponse(id=file_id.hex)

"""Durable, single-job-at-a-time vector store file ingestion."""

import asyncio
import logging
import os
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, text
from sqlalchemy.exc import OperationalError
from sqlmodel import select

from config import settings
from embedding_service import embedding_service
from classes.database import Embedding, File, VectorStore, VectorStoreFile, database_instance
from classes.document import Document
from classes.s3_file_handler import S3FileHandler


logger = logging.getLogger(__name__)
DEFAULT_CHUNKING_STRATEGY = {
    "type": "static",
    "static": {"max_chunk_size_tokens": 800, "chunk_overlap_tokens": 400},
}


class IngestionFailure(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def refresh_store_usage(session, store_id: UUID) -> None:
    """Recalculate counters from attachment rows in the current transaction."""
    store = session.get(VectorStore, store_id)
    if store is None:
        return
    counts = {key: 0 for key in ("in_progress", "completed", "failed", "cancelled", "total")}
    usage_bytes = 0
    rows = session.exec(
        select(VectorStoreFile.status, func.count(), func.coalesce(func.sum(VectorStoreFile.usage_bytes), 0))
        .where(VectorStoreFile.vector_store_id == store_id)
        .group_by(VectorStoreFile.status)
    ).all()
    for status, count, size in rows:
        if status in counts:
            counts[status] = int(count)
        counts["total"] += int(count)
        if status == "completed":
            usage_bytes += int(size)
    store.file_counts = counts
    store.usage_bytes = usage_bytes
    store.status = "in_progress" if counts["in_progress"] else "completed"
    store.last_active_at = datetime.now(timezone.utc).replace(tzinfo=None)
    session.add(store)


def _s3_handler() -> S3FileHandler:
    return S3FileHandler(
        region=settings.s3_region,
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key,
        bucket=settings.s3_bucket,
        host=settings.s3_host,
    )


def _parse_file(s3_key: str, strategy: dict) -> list[str]:
    # S3FileHandler uses a synchronous client under its async method. Run it and
    # the CPU-heavy document converter off the API event loop.
    filepath = asyncio.run(_s3_handler().get_file(s3_key))
    try:
        document = Document(filepath)
        options = strategy.get("static") or DEFAULT_CHUNKING_STRATEGY["static"]
        return document.compute_chunks(**options)
    finally:
        if os.path.exists(filepath):
            os.remove(filepath)


def _pending_jobs() -> list[UUID]:
    with database_instance.session() as session:
        return list(session.exec(
            select(VectorStoreFile.id)
            .where(VectorStoreFile.status == "in_progress")
            .order_by(VectorStoreFile.created_at, VectorStoreFile.id)
            .limit(50)
        ).all())


def _job_input(job_id: UUID) -> tuple[str, dict] | None:
    with database_instance.session() as session:
        job = session.get(VectorStoreFile, job_id)
        if job is None or job.status != "in_progress":
            return None
        file = session.get(File, job.file_id)
        if file is None:
            raise IngestionFailure("invalid_file", "The uploaded file no longer exists")
        return file.filename_on_disk, job.chunking_strategy_config or DEFAULT_CHUNKING_STRATEGY


def _finish_job(job_id: UUID, chunks: list[str], vectors: list[list[float]]) -> None:
    if len(chunks) != len(vectors):
        raise IngestionFailure("server_error", "Embedding response did not match the file chunks")

    with database_instance.session() as session:
        session.exec(text("SET LOCAL lock_timeout = '2s'"))
        job = session.exec(select(VectorStoreFile).where(VectorStoreFile.id == job_id).with_for_update()).first()
        if job is None or job.status != "in_progress":
            return
        # A crash during a previous attempt may have left embeddings behind.
        for embedding in session.exec(select(Embedding).where(Embedding.vector_store_file_id == job_id)).all():
            session.delete(embedding)
        session.flush()
        for chunk, vector in zip(chunks, vectors):
            session.add(Embedding(
                vector_store_id=job.vector_store_id,
                vector_store_file_id=job.id,
                content=chunk,
                embedding=vector,
                embedding_metadata=job.attributes or {},
            ))
        job.status = "completed"
        job.last_error = None
        job.usage_bytes = sum(len(chunk.encode("utf-8")) for chunk in chunks)
        session.add(job)
        session.flush()
        refresh_store_usage(session, job.vector_store_id)
        session.commit()


def _fail_job(job_id: UUID, code: str, message: str) -> None:
    with database_instance.session() as session:
        session.exec(text("SET LOCAL lock_timeout = '2s'"))
        job = session.exec(select(VectorStoreFile).where(VectorStoreFile.id == job_id).with_for_update()).first()
        if job is None or job.status != "in_progress":
            return
        job.status = "failed"
        job.last_error = {"code": code, "message": message}
        session.add(job)
        session.flush()
        refresh_store_usage(session, job.vector_store_id)
        session.commit()


async def _process_job(job_id: UUID) -> None:
    try:
        job_input = await asyncio.to_thread(_job_input, job_id)
        if job_input is None:
            return
        s3_key, strategy = job_input
        try:
            chunks = await asyncio.to_thread(_parse_file, s3_key, strategy)
        except Exception as exc:
            raise IngestionFailure("invalid_file", "Could not parse the uploaded file") from exc
        if not chunks:
            raise IngestionFailure("invalid_file", "The uploaded file contains no text")

        vectors: list[list[float]] = []
        # A server-side key lets queued jobs resume after an app restart without
        # persisting the requester's virtual key in the database.
        embedding_key = settings.litellm_api_key
        if not embedding_key:
            raise IngestionFailure("server_error", "Embedding service key is not configured")
        for start in range(0, len(chunks), 32):
            vectors.extend(await embedding_service.generate_embeddings(chunks[start:start + 32], embedding_key))
        await asyncio.to_thread(_finish_job, job_id, chunks, vectors)
    except asyncio.CancelledError:
        raise
    except IngestionFailure as exc:
        logger.warning("File ingestion failed for %s: %s", job_id, exc.message)
        await asyncio.to_thread(_fail_job, job_id, exc.code, exc.message)
    except OperationalError as exc:
        if getattr(exc.orig, "pgcode", None) == "55P03":
            logger.warning("Database row is locked; retrying ingestion for %s", job_id)
            return
        logger.exception("File ingestion failed for %s", job_id)
        await asyncio.to_thread(_fail_job, job_id, "server_error", "File ingestion failed")
    except Exception:
        logger.exception("File ingestion failed for %s", job_id)
        await asyncio.to_thread(_fail_job, job_id, "server_error", "File ingestion failed")


async def run_ingestion_worker() -> None:
    """Poll persisted jobs; PostgreSQL advisory locks coordinate app replicas."""
    while True:
        try:
            for job_id in await asyncio.to_thread(_pending_jobs):
                lock_id = int.from_bytes(job_id.bytes[:8], "big", signed=True)
                with database_instance._engine.connect() as connection:
                    acquired = connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": lock_id})
                    connection.rollback()
                    if not acquired:
                        continue
                    try:
                        await _process_job(job_id)
                    finally:
                        connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": lock_id})
                        connection.rollback()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Ingestion worker poll failed")
        await asyncio.sleep(2)

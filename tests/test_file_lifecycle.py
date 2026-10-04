"""Local HTTP + PostgreSQL + worker integration tests.

Set TEST_DATABASE_URL to a local PostgreSQL database with pgvector installed.
Each test run creates and removes its own schema.
"""

import asyncio
from contextlib import suppress
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlmodel import select


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.downloaded_paths = []

    async def upload_file(self, file, subdirectory):
        body = await file.read()
        key = f"{subdirectory}/{uuid4().hex}_{file.filename}"
        self.objects[key] = body
        await file.close()
        return {"s3_key": key, "bytes": len(body)}

    async def get_file(self, key):
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=Path(key).suffix, delete=False
        ) as destination:
            destination.write(self.objects[key])
            self.downloaded_paths.append(Path(destination.name))
            return destination.name

    async def delete_file(self, key):
        return self.objects.pop(key, None) is not None


class TextDocument:
    chunking_options = []

    def __init__(self, filepath):
        self.filepath = filepath

    def compute_chunks(self, **options):
        self.chunking_options.append(options)
        return [Path(self.filepath).read_text()]


class FileLifecycleIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base_url = os.environ.get("TEST_DATABASE_URL")
        if not base_url:
            raise unittest.SkipTest("Set TEST_DATABASE_URL to run local integration tests")
        parts = urlsplit(base_url)
        if parts.scheme not in {"postgresql", "postgres"} or parts.hostname not in {
            "127.0.0.1", "localhost", "::1"
        }:
            raise ValueError("TEST_DATABASE_URL must point to local PostgreSQL")
        if "classes.database" in sys.modules:
            raise RuntimeError("Run this integration suite in a fresh Python process")

        cls.schema = f"file_api_test_{uuid4().hex[:12]}"
        query = [(key, value) for key, value in parse_qsl(parts.query) if key != "schema"]
        query.append(("schema", cls.schema))
        cls.original_database_url = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
        )

        # Import after selecting the isolated schema: the app builds its engine
        # and tables when classes.database is first imported.
        from main import app
        from routers import files
        from classes import ingestion
        from classes.database import Database, Embedding, File, VectorStore, VectorStoreFile, database_instance
        from config import settings
        from util import get_litellm_vkey_info

        cls.app = app
        cls.files = files
        cls.ingestion = ingestion
        cls.Database = Database
        cls.Embedding = Embedding
        cls.File = File
        cls.VectorStore = VectorStore
        cls.VectorStoreFile = VectorStoreFile
        cls.db = database_instance
        cls.settings = settings
        cls.auth_dependency = get_litellm_vkey_info

    @classmethod
    def tearDownClass(cls):
        try:
            cls.app.dependency_overrides.pop(cls.auth_dependency, None)
            with cls.db._engine.begin() as connection:
                schema = connection.dialect.identifier_preparer.quote(cls.schema)
                connection.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
            cls.db._engine.dispose()
        finally:
            if cls.original_database_url is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = cls.original_database_url

    def setUp(self):
        self.user_id = f"test-{uuid4().hex}"
        self.key_info = {"info": {"user_id": self.user_id}, "key": "test-user-key"}
        self.app.dependency_overrides[type(self).auth_dependency] = lambda: self.key_info
        self.s3 = FakeS3()
        for target, attribute, value in (
            (self.files, "_s3_handler", lambda: self.s3),
            (self.ingestion, "_s3_handler", lambda: self.s3),
            (self.settings, "litellm_api_key", "test-server-key"),
        ):
            patcher = patch.object(target, attribute, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

        with self.db.session() as session:
            store = self.VectorStore(
                name="integration", user_id=self.user_id,
                file_counts={"in_progress": 0, "completed": 0, "failed": 0, "cancelled": 0, "total": 0},
                status="completed", usage_bytes=0,
            )
            session.add(store)
            session.commit()
            self.store_id = store.id

    def tearDown(self):
        with self.db.session() as session:
            store = session.get(self.VectorStore, self.store_id)
            if store is not None:
                session.delete(store)
            for file in session.exec(select(self.File).where(self.File.user_id == self.user_id)).all():
                session.delete(file)
            session.commit()
        for path in self.s3.downloaded_paths:
            path.unlink(missing_ok=True)

    def upload(self, body=b"README sample", path="/v1/files"):
        response = self.client.post(
            path,
            files={"file": ("README.md", body, "text/markdown")},
            data={"purpose": "assistants"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["bytes"], len(body))
        self.assertEqual(response.json()["object"], "file")
        return response.json()["id"]

    def attach(self, file_id, **extra):
        response = self.client.post(
            f"/v1/vector_stores/{self.store_id.hex}/files",
            json={"file_id": file_id, **extra},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["id"], file_id)
        self.assertEqual(response.json()["status"], "in_progress")
        return response.json()

    def attachment(self, file_id):
        return self.client.get(
            f"/v1/vector_stores/{self.store_id.hex}/files/{file_id}"
        )

    def run_worker_until(self, file_id, target_status):
        async def wait_for_job():
            worker = asyncio.create_task(self.ingestion.run_ingestion_worker())
            try:
                for _ in range(100):
                    with self.db.session() as session:
                        job = session.exec(
                            select(self.VectorStoreFile).where(
                                self.VectorStoreFile.vector_store_id == self.store_id,
                                self.VectorStoreFile.file_id == UUID(file_id),
                            )
                        ).first()
                        if job is not None and job.status == target_status:
                            return
                    await asyncio.sleep(0.1)
                self.fail(f"worker did not reach {target_status}")
            finally:
                worker.cancel()
                with suppress(asyncio.CancelledError):
                    await worker

        asyncio.run(wait_for_job())

    def test_upload_ingest_detach_and_delete(self):
        first_id = self.upload()
        second_id = self.upload(path="/files")
        self.assertNotEqual(first_id, second_id)  # Duplicate filenames are allowed.
        self.assertEqual(self.client.get(f"/v1/files/{first_id}").status_code, 200)

        strategy = {
            "type": "static",
            "static": {"max_chunk_size_tokens": 100, "chunk_overlap_tokens": 50},
        }
        attached = self.attach(
            first_id,
            attributes={"source": "readme"},
            chunking_strategy=strategy,
        )
        self.assertEqual(attached["chunking_strategy"], strategy)
        self.assertEqual(self.attachment(first_id).json()["status"], "in_progress")
        self.assertEqual(
            self.client.get(f"/v1/vector_stores/{self.store_id.hex}").json()["status"],
            "in_progress",
        )
        duplicate = self.client.post(
            f"/v1/vector_stores/{self.store_id.hex}/files",
            json={"file_id": first_id},
        )
        self.assertEqual(duplicate.status_code, 400)

        TextDocument.chunking_options = []
        async def embeddings(chunks, key):
            self.assertEqual(key, "test-server-key")
            return [[0.0] * 3072 for _ in chunks]

        with patch.object(self.ingestion, "Document", TextDocument), patch.object(
            self.ingestion.embedding_service, "generate_embeddings", side_effect=embeddings
        ):
            self.run_worker_until(first_id, "completed")

        result = self.attachment(first_id).json()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["usage_bytes"], len(b"README sample"))
        self.assertEqual(result["attributes"], {"source": "readme"})
        self.assertEqual(
            TextDocument.chunking_options,
            [{"max_chunk_size_tokens": 100, "chunk_overlap_tokens": 50}],
        )
        with self.db.session() as session:
            store = session.get(self.VectorStore, self.store_id)
            self.assertEqual(store.file_counts["completed"], 1)
            self.assertEqual(store.file_counts["in_progress"], 0)
            self.assertEqual(store.status, "completed")
            embeddings_rows = session.exec(
                select(self.Embedding).where(self.Embedding.vector_store_id == self.store_id)
            ).all()
            self.assertEqual(len(embeddings_rows), 1)
            self.assertEqual(embeddings_rows[0].embedding_metadata, {"source": "readme"})
        self.assertTrue(all(not path.exists() for path in self.s3.downloaded_paths))

        detached = self.client.delete(
            f"/v1/vector_stores/{self.store_id.hex}/files/{first_id}"
        )
        self.assertEqual(detached.status_code, 200, detached.text)
        self.assertEqual(detached.json()["object"], "vector_store.file.deleted")
        self.assertEqual(self.attachment(first_id).status_code, 404)
        self.assertEqual(self.client.get(f"/v1/files/{first_id}").status_code, 200)
        with self.db.session() as session:
            self.assertEqual(session.get(self.VectorStore, self.store_id).file_counts["total"], 0)
        self.assertEqual(self.client.delete(f"/v1/files/{first_id}").status_code, 200)
        self.assertEqual(self.client.delete(f"/v1/files/{second_id}").status_code, 200)
        self.assertFalse(self.s3.objects)

    def test_failed_ingestion_is_pollable(self):
        file_id = self.upload(body=b"invalid content")
        self.attach(file_id)
        with patch.object(self.ingestion, "Document", side_effect=ValueError("bad document")):
            self.run_worker_until(file_id, "failed")

        result = self.attachment(file_id).json()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["last_error"]["code"], "invalid_file")
        with self.db.session() as session:
            store = session.get(self.VectorStore, self.store_id)
            self.assertEqual(store.file_counts["failed"], 1)
            self.assertEqual(store.file_counts["in_progress"], 0)
        self.assertTrue(all(not path.exists() for path in self.s3.downloaded_paths))
        self.assertEqual(self.client.delete(f"/v1/files/{file_id}").status_code, 200)
        with self.db.session() as session:
            self.assertEqual(session.get(self.VectorStore, self.store_id).file_counts["total"], 0)

    def test_listing_pagination_and_owner_scope(self):
        first_id = self.upload(body=b"first")
        second_id = self.upload(body=b"second")
        self.attach(first_id)
        self.attach(second_id)
        base = f"/v1/vector_stores/{self.store_id.hex}/files"
        page = self.client.get(base, params={"limit": 1, "filter": "in_progress"})
        self.assertEqual(page.status_code, 200, page.text)
        self.assertTrue(page.json()["has_more"])
        next_page = self.client.get(
            base, params={"limit": 1, "after": page.json()["last_id"]}
        )
        self.assertEqual(next_page.status_code, 200, next_page.text)
        self.assertEqual(len(next_page.json()["data"]), 1)
        self.assertNotEqual(next_page.json()["data"][0]["id"], page.json()["data"][0]["id"])

        self.key_info["info"]["user_id"] = "another-user"
        self.assertEqual(self.attachment(first_id).status_code, 404)
        self.assertEqual(self.client.get(f"/v1/files/{first_id}").status_code, 404)
        self.key_info["info"]["user_id"] = self.user_id

    def test_existing_table_receives_new_columns(self):
        file_id = self.upload()
        self.attach(file_id)
        with self.db._engine.begin() as connection:
            schema = connection.dialect.identifier_preparer.quote(self.schema)
            connection.execute(text(
                f"ALTER TABLE {schema}.vectorstorefile "
                "DROP COLUMN status, DROP COLUMN last_error, "
                "DROP COLUMN chunking_strategy_config"
            ))
        migrated = self.Database()
        try:
            columns = {
                column["name"]
                for column in inspect(migrated._engine).get_columns(
                    "vectorstorefile", schema=self.schema
                )
            }
            self.assertTrue(
                {"status", "last_error", "chunking_strategy_config"} <= columns
            )
            with migrated.session() as session:
                job = session.exec(
                    select(self.VectorStoreFile).where(
                        self.VectorStoreFile.file_id == UUID(file_id)
                    )
                ).first()
                self.assertEqual(job.status, "completed")
        finally:
            migrated._engine.dispose()


if __name__ == "__main__":
    unittest.main()

import datetime, os
from fastapi import APIRouter, Depends, HTTPException, Form
from typing import Annotated

from models import (
    UploadFileRequest,
    UploadFileResponse,
    DeleteFileResponse,
    VectorStoreFileRequest,
    VectorStoreFileResponse,
    EmbeddingCreateRequest,
    VectorStoreFileDeleteResponse
)

from classes.s3_file_handler import S3FileHandler
from embedding_service import embedding_service
from util import (
    get_litellm_user_id,
    get_litellm_vkey_info,
    is_litellm_admin,
    scope_to_litellm_user,
)
from config import settings
from classes.database import database_instance, File, VectorStore, VectorStoreFile
from sqlmodel import select, col, text
from uuid import UUID
from classes.document import Document

router = APIRouter()

@router.post(
    "/files",
    response_model=UploadFileResponse,
)
async def upload_file(
    data: Annotated[UploadFileRequest, Form()],
    litellm_vkey_info = Depends(get_litellm_vkey_info),
):
    try:
        file = data.file
        if not file.size or not file.filename:
            raise HTTPException(status_code=500, detail="File upload failed")

        if is_litellm_admin(litellm_vkey_info):
            raise HTTPException(
                status_code=400,
                detail="Upload a file with the LiteLLM user's API key, not the admin key",
            )
        user = get_litellm_user_id(litellm_vkey_info)

        session = database_instance.session()
        existing_file_statement = select(File).where(File.filename == file.filename)
        existing_file_statement = existing_file_statement.where(File.user_id == user)

        existing_file_result = session.exec(existing_file_statement).first()

        if existing_file_result:
            raise HTTPException(status_code=500, detail="This file already exists. Please provide a file with a different name.")

        # TODO replace with call that creates a s3 or local file handler, depending on configuration
        s3_file_handler = S3FileHandler(
            region=settings.s3_region,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            bucket=settings.s3_bucket,
            host=settings.s3_host
            )

        upload_res = await s3_file_handler.upload_file(file, f"user/{user}")

        new_file = File(
            user_id=user,
            team_id=None,
            filename=file.filename,
            size=file.size,
            purpose=data.purpose,
            created_at=datetime.datetime.now(),
            expires_at=None,
            filename_on_disk=upload_res['s3_key']
        )

        session.add(new_file)
        session.commit()
        session.refresh(new_file)
        session.close()

        return UploadFileResponse(
            id=new_file.id.hex,
            bytes=file.size,
            created_at=int(new_file.created_at.timestamp()),
            filename=file.filename,
            purpose=data.purpose,
            object="file",
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback

        traceback.print_exc()
        raise HTTPException(
            status_code=500, detail=f"Failed to create embedding: {str(e)}"
        )

@router.delete("/v1/files/{file_id}", response_model=DeleteFileResponse)
async def delete_file(
    file_id: str,
    litellm_vkey_info = Depends(get_litellm_vkey_info)    
):
    """
    Delete a file, from storage aswell as from all vector stores.
    """
    try:
        session = database_instance.session()
        statement = select(File).where(col(File.id) == UUID(file_id))
        statement = scope_to_litellm_user(statement, File, litellm_vkey_info)

        file = session.exec(statement).first()
        if not file:
            raise HTTPException(status_code=404, detail="File not found")

        # TODO replace with call that creates a s3 or local file handler, depending on configuration
        s3_file_handler = S3FileHandler(
            region=settings.s3_region,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            bucket=settings.s3_bucket,
            host=settings.s3_host
            )

        await s3_file_handler.delete_file(file.filename_on_disk)

        for vector_store_file in file.vector_store_files:
            database_instance.update_vector_store_statistics(
                vector_store_id=vector_store_file.vector_store_id.hex,
                litellm_vkey_info=litellm_vkey_info,
                completed=-1,
                usage_bytes=-vector_store_file.usage_bytes
            )

        session.delete(file)
        session.commit()
        return DeleteFileResponse(id=file_id)

    except HTTPException:
        session.rollback()
        raise
    except Exception as e:
        import traceback

        traceback.print_exc()
        raise HTTPException(
            status_code=500, detail=f"Failed to create embedding: {str(e)}"
        )
    finally:
        session.close()

@router.post(
    "/v1/vector_stores/{vector_store_id}/files",
    response_model=VectorStoreFileResponse,
)
async def create_vector_store_file(
    vector_store_id: str,
    request: VectorStoreFileRequest,
    litellm_vkey_info = Depends(get_litellm_vkey_info),
):
    try:
        # Check if vector store exists
        # TODO deduplicate
        statement = select(VectorStore).where(col(VectorStore.id) == UUID(vector_store_id))
        statement = scope_to_litellm_user(statement, VectorStore, litellm_vkey_info)

        session = database_instance.session()
        vector_store = session.exec(statement).first()
        if not vector_store:
            raise HTTPException(status_code=404, detail="Vector store not found")

        file_statement = select(File).where(col(File.id) == UUID(request.file_id))
        file_statement = file_statement.where(File.user_id == vector_store.user_id)
        requested_file = session.exec(file_statement).first()
        if not requested_file:
            raise HTTPException(status_code=404, detail="File not found")

        vector_store_file_exists_statement = select(VectorStoreFile).where(col(File.id) == UUID(request.file_id)).where(col(VectorStore.id) == UUID(vector_store_id))
        vector_store_file_exists_result = session.exec(vector_store_file_exists_statement).first()
        if vector_store_file_exists_result:
            raise HTTPException(status_code=400, detail="This file has already been inserted into the vector store.")

        litellm_vkey = litellm_vkey_info['key']

        s3_file_handler = S3FileHandler(
            region=settings.s3_region,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            bucket=settings.s3_bucket,
            host=settings.s3_host
            )

        filepath = await s3_file_handler.get_file(requested_file.filename_on_disk)
        try:
            document = Document(filepath)
        except Exception as e:
            # TODO handle error
            raise HTTPException(500, f"Could not ingest provided file: {e}")

        os.remove(filepath)

        chunk_texts = document.compute_chunks()

        embedding_vectors = await embedding_service.generate_embeddings(chunk_texts, litellm_vkey)
        embedding_create_requests = []

        usage_bytes = 0
        for index, chunk_text in enumerate(chunk_texts):
            embedding_create_requests.append(
                EmbeddingCreateRequest(
                    content=chunk_text,
                    embedding=embedding_vectors[index],
                )
            )
            usage_bytes += len(chunk_text)

        new_vector_store_file = VectorStoreFile(
            file_id=UUID(request.file_id),
            user_id=vector_store.user_id,
            team_id=None,
            vector_store_id=UUID(vector_store_id),
            attributes=None,
            chunking_strategy="static",
            created_at=datetime.datetime.now(),
            usage_bytes=usage_bytes,
        )

        session.add(new_vector_store_file)
        session.commit()
        # session.refresh(new_vector_store_file)

        database_instance.update_vector_store_statistics(
            vector_store_id=vector_store_id,
            litellm_vkey_info=litellm_vkey_info,
            completed=1,
            usage_bytes=usage_bytes
        )

        embedding_result = await embedding_service.insert_embeddings(
            vector_store_id=vector_store_id, 
            vector_store_file_id=new_vector_store_file.id.hex, 
            embeddings=embedding_create_requests, 
            litellm_vkey_info=litellm_vkey_info
        )

        new_vector_store_file.usage_bytes = embedding_result.total_content_length
        session.add(new_vector_store_file)
        session.commit()

        return VectorStoreFileResponse(
            id=new_vector_store_file.id.hex,
            created_at=int(new_vector_store_file.created_at.timestamp()),
            object="vector_store.file",
            status="completed",
            usage_bytes=embedding_result.total_content_length,
            vector_store_id=vector_store_id,
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback

        traceback.print_exc()
        raise HTTPException(
            status_code=500, detail=f"Failed to create embedding: {str(e)}"
        )

@router.delete('/vector_stores/{vector_store_id}/files/{file_id}', response_model=VectorStoreFileDeleteResponse)
async def delete_vector_store_file(
    vector_store_id: str,
    file_id: str,
    litellm_vkey_info = Depends(get_litellm_vkey_info),
):
    try:
        session = database_instance.session()
        statement = select(VectorStoreFile).where(col(VectorStoreFile.vector_store_id) == UUID(vector_store_id)).where(col(VectorStoreFile.id) == UUID(file_id))
        statement = scope_to_litellm_user(statement, File, litellm_vkey_info)

        file = session.exec(statement).first()
        if not file:
            raise HTTPException(status_code=404, detail="File not found")

        session.delete(file)
        session.commit()    

        database_instance.update_vector_store_statistics(
            vector_store_id=vector_store_id, 
            litellm_vkey_info=litellm_vkey_info,
            completed=-1,
            usage_bytes=-file.usage_bytes
            )

        return VectorStoreFileDeleteResponse(
            id=file_id,
            deleted=True,
        )
    except HTTPException:
        session.rollback()
        raise
    except Exception as e:
        import traceback

        traceback.print_exc()
        raise HTTPException(
            status_code=500, detail=f"Failed to delete vector store file: {str(e)}"
        )
    finally:
        session.close()
        pass
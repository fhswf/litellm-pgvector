import asyncio
import datetime, os
from fastapi import APIRouter, Depends, HTTPException, Form
from typing import Annotated, Optional
from sqlmodel import select, col, desc
from sqlalchemy import label
from uuid import UUID

from models import (
    VectorStoreResponse,
    VectorStoreCreateRequest,
    VectorStoreListResponse,
    VectorStoreSearchResponse,
    VectorStoreSearchRequest,
    SearchResult,
    ContentChunk,
    VectorStoreDeleteResponse,
    VectorStoreUpdateRequest,
    VectorStoreUpdateResponse
)

from util import get_litellm_user_id, get_litellm_vkey_info, is_litellm_admin
from litellm_registry import (
    LiteLLMRegistryError,
    delete_registered_vector_store,
    register_vector_store,
)

from embedding_service import embedding_service

from classes.database import VectorStore, database_instance, Embedding

router = APIRouter()


def _scope_to_owner(statement, model, litellm_vkey_info):
    if is_litellm_admin(litellm_vkey_info):
        return statement
    return statement.where(model.user_id == get_litellm_user_id(litellm_vkey_info))


def _search_store_id(vector_store_id: UUID, litellm_vkey_info: dict) -> UUID:
    statement = select(VectorStore).where(col(VectorStore.id) == vector_store_id)
    statement = _scope_to_owner(statement, VectorStore, litellm_vkey_info)
    with database_instance.session() as session:
        store = session.exec(statement).first()
        if store is None:
            raise HTTPException(status_code=404, detail="Vector store not found")
        return store.id


def _search_embeddings(statement):
    with database_instance.session() as session:
        return session.exec(statement).all()

@router.post("/v1/vector_stores", response_model=VectorStoreResponse)
async def create_vector_store(
    request: VectorStoreCreateRequest, litellm_vkey_info = Depends(get_litellm_vkey_info),

):
    """
    Create a new vector store.
    """
    if is_litellm_admin(litellm_vkey_info):
        raise HTTPException(
            status_code=400,
            detail="Create a vector store with the LiteLLM user's API key, not the admin key",
        )

    user = get_litellm_user_id(litellm_vkey_info)
    session = database_instance.session()
    store = VectorStore(
        name=request.name,
        user_id=user,
        team_id=None,
        file_counts={"in_progress": 0, "completed": 0, "failed": 0, "cancelled": 0, "total": 0},
        status="completed",
        usage_bytes=0,
        expires_after=request.expires_after,
        store_metadata=request.metadata or {},
    )

    try:
        session.add(store)
        session.commit()
        session.refresh(store)

        try:
            await register_vector_store(
                vector_store_id=store.id.hex,
                name=store.name,
                owner_key=litellm_vkey_info["key"],
                owner_info=litellm_vkey_info["info"],
                metadata=store.store_metadata,
            )
        except LiteLLMRegistryError as exc:
            session.delete(store)
            session.commit()
            raise HTTPException(
                status_code=502,
                detail=f"Vector store was not registered in LiteLLM: {exc}",
            ) from exc

        created_at = int(store.created_at.timestamp())
        expires_at = (
            int(store.expires_at.timestamp())
            if store.expires_at
            else None
        )
        last_active_at = (
            int(store.last_active_at.timestamp())
            if store.last_active_at
            else None
        )

        return VectorStoreResponse(
            id=store.id.hex,
            created_at=created_at,
            name=store.name,
            usage_bytes=store.usage_bytes or 0,
            file_counts=store.file_counts
            or {
                "in_progress": 0,
                "completed": 0,
                "failed": 0,
                "cancelled": 0,
                "total": 0,
            },
            status=store.status,
            expires_after=store.expires_after,
            expires_at=expires_at,
            last_active_at=last_active_at,
            metadata=store.store_metadata
        )

    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        raise HTTPException(
            status_code=500, detail=f"Failed to create vector store: {str(e)}"
        )
    finally:
        session.close()

@router.get("/v1/vector_stores", response_model=VectorStoreListResponse)
async def list_vector_stores(
    limit: Optional[int] = 20,
    after: Optional[str] = None,
    before: Optional[str] = None,
    litellm_vkey_info = Depends(get_litellm_vkey_info),
):
    """
    List vector stores with optional pagination.
    """
    try:
        limit = min(limit or 20, 100)  # Cap at 100 results

        statement = select(VectorStore)

        if after:
            statement = statement.where(col(VectorStore.id) > UUID(after))

        if before:
            statement = statement.where(col(VectorStore.id) < UUID(before))

        statement = _scope_to_owner(statement, VectorStore, litellm_vkey_info)

        statement = statement.order_by(desc(VectorStore.created_at)).limit(limit + 1)

        session = database_instance.session()
        res = session.exec(statement)
        stores = res.all()
        session.close()

        # Check if there are more results
        has_more = len(stores) > limit
        if has_more:
            stores = stores[:limit]  # Remove extra result

        # Convert to response format
        vector_stores = []
        for store in stores:
            created_at = int(store.created_at.timestamp())
            expires_at = int(store.expires_at.timestamp()) if store.expires_at else None
            last_active_at = int(store.last_active_at.timestamp()) if store.last_active_at else None

            vector_store = VectorStoreResponse(
                id=store.id.hex,
                created_at=created_at,
                name=store.name,
                usage_bytes=store.usage_bytes or 0,
                file_counts=store.file_counts
                or {
                    "in_progress": 0,
                    "completed": 0,
                    "failed": 0,
                    "cancelled": 0,
                    "total": 0,
                },
                status=store.status,
                expires_after=store.expires_after,
                expires_at=expires_at,
                last_active_at=last_active_at,
                metadata=store.store_metadata,
            )
            vector_stores.append(vector_store)

        first_id = vector_stores[0].id if vector_stores else None
        last_id = vector_stores[-1].id if vector_stores else None

        return VectorStoreListResponse(
            data=vector_stores, first_id=first_id, last_id=last_id, has_more=has_more
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        raise HTTPException(
            status_code=500, detail=f"Failed to list vector stores: {str(e)}"
        )

@router.post(
    "/v1/vector_stores/{vector_store_id}/search",
    response_model=VectorStoreSearchResponse,
)
@router.post(
    "/vector_stores/{vector_store_id}/search", response_model=VectorStoreSearchResponse
)
async def search_vector_store(
    vector_store_id: str,
    request: VectorStoreSearchRequest,
    litellm_vkey_info = Depends(get_litellm_vkey_info),
    ):
    """
    Search a vector store for similar content.
    """
    try:
        store_id = await asyncio.to_thread(
            _search_store_id, UUID(vector_store_id), litellm_vkey_info
        )

        # Generate embedding for query
        query_embedding = await embedding_service.generate_embedding(request.query, litellm_vkey_info['key'])
        query_embedding = query_embedding + [0] * (3072 - len(query_embedding))

        # Build the raw SQL query for vector similarity search
        limit = min(request.limit or 20, 100)  # Cap at 100 results

        embedding_statement = select(
            Embedding.id, 
            Embedding.content, 
            Embedding.embedding_metadata, 
            Embedding.embedding.l2_distance(query_embedding).label('distance') # pyright: ignore[reportAttributeAccessIssue]
            ).where(col(Embedding.vector_store_id) == store_id)

        if request.filters:
            for key, value in request.filters.items():
                embedding_statement = embedding_statement.where(col(Embedding.embedding_metadata)[key].as_string() == value)


        embedding_statement = embedding_statement.order_by(label('distance', col(Embedding.embedding)).asc()).limit(limit)
        embedding_results = await asyncio.to_thread(_search_embeddings, embedding_statement)

        # Convert results to SearchResult objects
        search_results = []
        for embedding_result in embedding_results:
            # Convert distance to similarity score (1 - normalized_distance)
            # Cosine distance ranges from 0 (identical) to 2 (opposite)
            similarity_score = max(0, 1 - (embedding_result[3] / 2))

            # Extract filename from metadata or use a default
            metadata = embedding_result[2] or {}
            if not metadata:
                filename = "document.txt"
            else:
                filename = metadata.get("filename", "document.txt") # pyright: ignore[reportAttributeAccessIssue]

            content_chunks = [ContentChunk(type="text", text=embedding_result[1])]

            result = SearchResult(
                file_id=embedding_result[0].hex,
                filename=filename,
                score=similarity_score,
                attributes=metadata if (request.return_metadata and metadata) else None, # pyright: ignore[reportArgumentType]
                content=content_chunks,
            )
            search_results.append(result)

        return VectorStoreSearchResponse(
            search_query=request.query,
            data=search_results,
            has_more=False,  # TODO: Implement pagination
            next_page=None,
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")

@router.delete("/vector_stores/{vector_store_id}/", response_model=VectorStoreDeleteResponse)
async def delete_vector_store(vector_store_id: str, litellm_vkey_info = Depends(get_litellm_vkey_info)):
    try:
        statement = select(VectorStore).where(col(VectorStore.id) == UUID(vector_store_id))
        statement = _scope_to_owner(statement, VectorStore, litellm_vkey_info)

        session = database_instance.session()
        res = session.exec(statement)
        store = res.first()

        if not store:
            raise HTTPException(status_code=404, detail="Vector store not found")

        try:
            await delete_registered_vector_store(store.id.hex)
        except LiteLLMRegistryError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Could not remove the vector store from LiteLLM: {exc}",
            ) from exc

        session.delete(store)
        session.commit()
        session.close()

        return VectorStoreDeleteResponse(id=store.id.hex)

    except HTTPException:
        raise
    except Exception as e:
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


@router.get("/v1/vector_stores/{vector_store_id}", response_model=VectorStoreResponse)
@router.get("/vector_stores/{vector_store_id}/", response_model=VectorStoreResponse, include_in_schema=False)
async def retrieve_vector_store(vector_store_id: str, litellm_vkey_info = Depends(get_litellm_vkey_info)):
    try:
        statement = select(VectorStore).where(col(VectorStore.id) == UUID(vector_store_id))
        statement = _scope_to_owner(statement, VectorStore, litellm_vkey_info)

        session = database_instance.session()
        res = session.exec(statement)
        store = res.first()
        session.close()
        if not store:
            raise HTTPException(status_code=404, detail="Vector store not found")

        return VectorStoreResponse(
            id=store.id.hex,
            name=store.name,
            created_at=int(store.created_at.timestamp()),
            file_counts=store.file_counts,
            usage_bytes=store.usage_bytes or 0,
            status=store.status,
            expires_after=store.expires_after,
            expires_at=int(store.expires_at.timestamp()) if store.expires_at else None,
            last_active_at=int(store.last_active_at.timestamp()) if store.last_active_at else None,
            metadata=store.store_metadata,
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")

@router.post("/vector_stores/{vector_store_id}/", response_model=VectorStoreUpdateResponse)
async def update_vector_store(vector_store_id: str, request: VectorStoreUpdateRequest, litellm_vkey_info = Depends(get_litellm_vkey_info)):
    try:
        statement = select(VectorStore).where(col(VectorStore.id) == UUID(vector_store_id))
        statement = _scope_to_owner(statement, VectorStore, litellm_vkey_info)

        session = database_instance.session()
        res = session.exec(statement)
        store = res.first()
        if not store:
            raise HTTPException(status_code=404, detail="Vector store not found")

        if request.name:
            store.name = request.name

        if request.expires_after:
            store.expires_after = request.expires_after

        if request.metadata:
            store.store_metadata = request.metadata

        session.add(store)
        session.commit()
        session.close()

        return VectorStoreUpdateResponse(
            id=store.id.hex,
            name=store.name,
            created_at=int(store.created_at.timestamp()),
            file_counts=store.file_counts,
            usage_bytes=store.usage_bytes or 0
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")

import hashlib
from pathlib import PurePath

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.rate_limit import limit_assistant_chat, limit_document_ingestion
from app.schemas import (
    AssistantChatRequest,
    AssistantChatResponse,
    AssistantDocumentCreate,
    AssistantDocumentRead,
    AssistantStatusRead,
)
from app.services.ai_provider import (
    AIConfigurationError,
    AIProviderError,
    OpenAICompatibleProvider,
)
from app.services.assistant import (
    ShopAssistant,
    detect_language,
    get_ai_provider,
    get_rag_store,
)
from app.services.rag import (
    DuplicateDocumentError,
    RAGDocumentError,
    RAGStore,
    split_text,
)

router = APIRouter(prefix="/assistant", tags=["AI assistant"])
SUPPORTED_DOCUMENT_SUFFIXES = {".txt", ".md", ".csv"}


@router.get(
    "/status",
    response_model=AssistantStatusRead,
    summary="Check optional AI configuration",
    description=(
        "Show whether chat and document embeddings are configured. This "
        "endpoint does not expose provider URLs, model credentials, or keys."
    ),
)
def get_assistant_status(
    provider: OpenAICompatibleProvider = Depends(get_ai_provider),
) -> AssistantStatusRead:
    return AssistantStatusRead(
        chat_configured=provider.settings.chat_configured,
        embeddings_configured=provider.settings.embeddings_configured,
    )


@router.post(
    "/chat",
    dependencies=[Depends(limit_assistant_chat)],
    response_model=AssistantChatResponse,
    summary="Ask the SmartBill assistant",
    description=(
        "Answer an English or Telugu question using approved read-only sales, "
        "invoice, product, customer, or document functions. Financial figures "
        "are calculated by backend services, not by the language model."
    ),
    responses={
        401: {"description": "Owner sign-in is required."},
        422: {"description": "The question is empty or too long."},
        502: {"description": "The configured provider failed or returned an invalid plan."},
        503: {"description": "The optional AI provider is not configured or available."},
    },
)
async def post_assistant_chat(
    payload: AssistantChatRequest,
    db: Session = Depends(get_db),
    provider: OpenAICompatibleProvider = Depends(get_ai_provider),
    store: RAGStore = Depends(get_rag_store),
) -> AssistantChatResponse:
    if not payload.question:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Question cannot be blank.",
        )
    try:
        result = await ShopAssistant(provider, store).answer(payload.question, db)
    except AIConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    except AIProviderError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        ) from error
    return AssistantChatResponse(
        answer=result.answer,
        language=detect_language(payload.question),
        intent=result.intent,
        sources=result.sources,
    )


@router.get(
    "/documents",
    response_model=list[AssistantDocumentRead],
    summary="List ingested shop documents",
)
def list_assistant_documents(
    store: RAGStore = Depends(get_rag_store),
) -> list[AssistantDocumentRead]:
    return [
        AssistantDocumentRead.model_validate(document)
        for document in store.list_documents()
    ]


@router.post(
    "/documents",
    dependencies=[Depends(limit_document_ingestion)],
    response_model=AssistantDocumentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest a text shop document",
    description=(
        "Store and index UTF-8 Markdown, CSV, or plain-text content. Document "
        "embeddings are sent to the configured external provider; the RAG "
        "database is separate from the billing database."
    ),
    responses={
        409: {"description": "This exact document was already ingested."},
        422: {"description": "The filename or document content is invalid."},
        503: {"description": "An embeddings model is not configured."},
    },
)
async def ingest_assistant_document(
    payload: AssistantDocumentCreate,
    provider: OpenAICompatibleProvider = Depends(get_ai_provider),
    store: RAGStore = Depends(get_rag_store),
) -> AssistantDocumentRead:
    filename = payload.filename.strip()
    if (
        not filename
        or PurePath(filename).name != filename
        or "/" in filename
        or "\\" in filename
        or PurePath(filename).suffix.lower() not in SUPPORTED_DOCUMENT_SUFFIXES
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Use a plain filename ending in .txt, .md, or .csv.",
        )
    if "\x00" in payload.content or not payload.content.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Document content must be non-empty UTF-8 text.",
        )
    try:
        chunks = split_text(payload.content)
        embeddings = await provider.embed(chunks)
        content_hash = hashlib.sha256(
            payload.content.encode("utf-8")
        ).hexdigest()
        document_id, created_at = store.add_document(
            filename, content_hash, chunks, embeddings
        )
    except DuplicateDocumentError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from error
    except RAGDocumentError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error
    except AIConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    except AIProviderError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        ) from error
    return AssistantDocumentRead(
        id=document_id,
        filename=filename,
        created_at=created_at,
        chunk_count=len(chunks),
    )


@router.delete(
    "/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove an ingested shop document",
    responses={404: {"description": "Document not found."}},
)
def delete_assistant_document(
    document_id: int = Path(gt=0),
    store: RAGStore = Depends(get_rag_store),
) -> None:
    if not store.delete_document(document_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

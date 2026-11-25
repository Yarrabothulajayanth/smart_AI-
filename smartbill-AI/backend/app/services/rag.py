import json
import math
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.database import DATABASE_PATH

MAX_DOCUMENT_CHARS = 1_000_000
CHUNK_SIZE = 900
CHUNK_OVERLAP = 120
MAX_CHUNKS_PER_DOCUMENT = 2_000
MAX_DOCUMENTS = 200
MAX_TOTAL_CHUNKS = 20_000


class RAGDocumentError(Exception):
    pass


class DuplicateDocumentError(RAGDocumentError):
    pass


@dataclass(frozen=True)
class RetrievedChunk:
    document_id: int
    filename: str
    chunk_number: int
    text: str
    score: float


def split_text(text: str) -> list[str]:
    cleaned = text.strip()
    if not cleaned:
        raise RAGDocumentError("Document text cannot be empty.")
    if len(cleaned) > MAX_DOCUMENT_CHARS:
        raise RAGDocumentError("Document text exceeds the 1 MB size limit.")

    chunks: list[str] = []
    start = 0
    while start < len(cleaned):
        end = min(start + CHUNK_SIZE, len(cleaned))
        if end < len(cleaned):
            boundary = cleaned.rfind(" ", start, end)
            if boundary > start + CHUNK_SIZE // 2:
                end = boundary
        chunk = cleaned[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(cleaned):
            break
        start = max(start + 1, end - CHUNK_OVERLAP)

    if len(chunks) > MAX_CHUNKS_PER_DOCUMENT:
        raise RAGDocumentError("Document contains too many text chunks.")
    return chunks


class RAGStore:
    def __init__(self, database_path: Path | None = None) -> None:
        configured_path = os.environ.get("SMARTBILL_RAG_DB_PATH", "").strip()
        default_path = Path(__file__).resolve().parents[2] / "assistant_rag.sqlite"
        selected_path = database_path or (
            Path(configured_path).expanduser() if configured_path else default_path
        )
        self.database_path = selected_path.resolve()
        if self.database_path == DATABASE_PATH.resolve():
            raise ValueError(
                "The RAG database must be separate from the billing database."
            )

    def _connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS rag_documents (
                id INTEGER PRIMARY KEY,
                filename TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(filename, content_hash)
            );
            CREATE TABLE IF NOT EXISTS rag_chunks (
                id INTEGER PRIMARY KEY,
                document_id INTEGER NOT NULL
                    REFERENCES rag_documents(id) ON DELETE CASCADE,
                chunk_number INTEGER NOT NULL,
                content TEXT NOT NULL,
                embedding TEXT NOT NULL,
                UNIQUE(document_id, chunk_number)
            );
            """
        )
        return connection

    def add_document(
        self,
        filename: str,
        content_hash: str,
        chunks: list[str],
        embeddings: list[list[float]],
    ) -> tuple[int, str]:
        if len(chunks) != len(embeddings):
            raise RAGDocumentError("Each document chunk must have one embedding.")
        if not chunks:
            raise RAGDocumentError("Document has no searchable text.")

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            document_count, chunk_count = connection.execute(
                "SELECT COUNT(*), (SELECT COUNT(*) FROM rag_chunks) "
                "FROM rag_documents"
            ).fetchone()
            if document_count >= MAX_DOCUMENTS:
                raise RAGDocumentError(
                    f"The document limit of {MAX_DOCUMENTS} has been reached."
                )
            if chunk_count + len(chunks) > MAX_TOTAL_CHUNKS:
                raise RAGDocumentError(
                    "The total searchable document size limit has been reached."
                )
            cursor = connection.execute(
                "INSERT INTO rag_documents (filename, content_hash, created_at) "
                "VALUES (?, ?, ?)",
                (
                    filename,
                    content_hash,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            document_id = int(cursor.lastrowid)
            connection.executemany(
                "INSERT INTO rag_chunks "
                "(document_id, chunk_number, content, embedding) "
                "VALUES (?, ?, ?, ?)",
                [
                    (
                        document_id,
                        index,
                        chunk,
                        json.dumps(vector, separators=(",", ":")),
                    )
                    for index, (chunk, vector) in enumerate(
                        zip(chunks, embeddings, strict=True)
                    )
                ],
            )
            connection.commit()
        except sqlite3.IntegrityError as error:
            if "UNIQUE constraint failed: rag_documents.filename" in str(error):
                raise DuplicateDocumentError(
                    "This exact document has already been ingested."
                ) from error
            raise
        finally:
            connection.close()

        return document_id, datetime.now(timezone.utc).isoformat()

    def list_documents(self) -> list[dict[str, object]]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT d.id, d.filename, d.created_at, COUNT(c.id) AS chunk_count "
                "FROM rag_documents AS d JOIN rag_chunks AS c ON c.document_id = d.id "
                "GROUP BY d.id ORDER BY d.created_at DESC, d.id DESC"
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def delete_document(self, document_id: int) -> bool:
        connection = self._connect()
        try:
            with connection:
                cursor = connection.execute(
                    "DELETE FROM rag_documents WHERE id = ?", (document_id,)
                )
                return cursor.rowcount > 0
        finally:
            connection.close()

    def search(
        self, query_embedding: list[float], limit: int = 5
    ) -> list[RetrievedChunk]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT c.document_id, d.filename, c.chunk_number, "
                "c.content, c.embedding FROM rag_chunks AS c "
                "JOIN rag_documents AS d ON d.id = c.document_id"
            ).fetchall()
        finally:
            connection.close()

        scored: list[RetrievedChunk] = []
        for row in rows:
            try:
                vector = json.loads(row["embedding"])
            except json.JSONDecodeError as error:
                raise RAGDocumentError("Stored document embedding is invalid.") from error
            score = cosine_similarity(query_embedding, vector)
            if score > 0:
                scored.append(
                    RetrievedChunk(
                        document_id=int(row["document_id"]),
                        filename=str(row["filename"]),
                        chunk_number=int(row["chunk_number"]),
                        text=str(row["content"]),
                        score=score,
                    )
                )
        return sorted(scored, key=lambda item: item.score, reverse=True)[:limit]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True)) / (
        left_norm * right_norm
    )

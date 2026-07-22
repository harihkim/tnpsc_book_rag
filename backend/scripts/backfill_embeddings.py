"""Retroactively generate embeddings for documents stuck in 'chunking' state.

Usage:
    cd backend
    PYTHONPATH="" uv run python scripts/backfill_embeddings.py

This script:
1. Finds all documents in 'chunking' state with chunks but no embeddings
2. Generates embeddings using BGE-small-en-v1.5
3. Activates the documents (state -> ready, sets activated_at)
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tnpsc_book_rag.config import get_settings
from tnpsc_book_rag.database_persistence.database import create_database
from tnpsc_book_rag.database_persistence.models import (
    BookDocumentRecord,
    ChunkEmbeddingRecord,
    ChunkRecord,
    ContentUnitRecord,
)
from tnpsc_book_rag.rag_adapters.embeddings import EmbeddingService


async def backfill_embeddings() -> None:
    settings = get_settings()
    database = create_database(settings)

    if database is None:
        print("ERROR: Database not configured")
        return

    embedding_service = EmbeddingService(
        model_identifier=settings.embedding_model_identifier,
        model_revision=settings.embedding_model_revision,
        device=settings.embedding_device,
        batch_size=settings.embedding_batch_size,
    )

    print(f"Embedding model: {embedding_service.model_identifier}")
    print(f"Device: {settings.embedding_device}")
    print()

    async with database.sessions() as session:
        # Find documents in 'chunking' state
        stmt = select(BookDocumentRecord).where(
            BookDocumentRecord.state == "chunking"
        )
        result = await session.execute(stmt)
        documents = result.scalars().all()

        if not documents:
            print("No documents in 'chunking' state found.")
            return

        print(f"Found {len(documents)} document(s) in 'chunking' state")

        for doc in documents:
            print(f"\nProcessing: {doc.source_filename} (id={doc.id})")

            # Get chunks for this document that don't have embeddings
            chunk_stmt = (
                select(ChunkRecord)
                .join(ContentUnitRecord, ContentUnitRecord.id == ChunkRecord.content_unit_id)
                .where(ChunkRecord.document_id == doc.id)
                .where(ContentUnitRecord.retrieval_eligible.is_(True))
            )
            chunk_result = await session.execute(chunk_stmt)
            chunks = chunk_result.scalars().all()

            if not chunks:
                print(f"  No retrieval-eligible chunks found, skipping")
                continue

            # Check which chunks already have embeddings
            existing_stmt = select(ChunkEmbeddingRecord.chunk_id).where(
                ChunkEmbeddingRecord.chunk_id.in_([c.id for c in chunks])
            )
            existing_result = await session.execute(existing_stmt)
            existing_ids = {row[0] for row in existing_result.all()}

            chunks_needing_embeddings = [c for c in chunks if c.id not in existing_ids]

            if not chunks_needing_embeddings:
                print(f"  All {len(chunks)} chunks already have embeddings")
            else:
                print(f"  Generating embeddings for {len(chunks_needing_embeddings)} chunks...")

                # Generate embeddings
                texts = [chunk.embedding_text for chunk in chunks_needing_embeddings]
                batch = embedding_service.embed_texts(texts)

                # Store embeddings
                for chunk, vector, checksum in zip(
                    chunks_needing_embeddings, batch.vectors, batch.content_checksums
                ):
                    session.add(
                        ChunkEmbeddingRecord(
                            chunk_id=chunk.id,
                            model_identifier=batch.model_identifier,
                            model_revision=batch.model_revision,
                            dimension=batch.dimension,
                            content_sha256=checksum,
                            embedding=vector,
                        )
                    )

                print(f"  Created {len(chunks_needing_embeddings)} embeddings")

            # Activate the document
            from datetime import UTC, datetime

            doc.state = "ready"
            doc.activated_at = datetime.now(UTC)
            print(f"  Document activated (state=ready)")

        await session.commit()
        print(f"\nDone! Processed {len(documents)} document(s)")


if __name__ == "__main__":
    asyncio.run(backfill_embeddings())

"""Deterministic structure-aware chunking for extracted pages."""

import hashlib
import re

from tnpsc_extraction.models import ChunkContentType, ExtractedBlock, ExtractedChunk, ExtractedPage

_TOKEN = re.compile(r"\w+|[^\w\s]", re.UNICODE)


def token_count(text: str) -> int:
    """Return a conservative deterministic token estimate for the 512-token MVP limit."""
    return max(1, len(_TOKEN.findall(text)))


def _content_type(blocks: list[ExtractedBlock]) -> ChunkContentType:
    values = {block.content_type for block in blocks}
    if len(values) == 1:
        value = next(iter(values))
        return {
            "heading": ChunkContentType.HEADING,
            "list": ChunkContentType.LIST,
            "table": ChunkContentType.TABLE,
            "caption": ChunkContentType.CAPTION,
            "prose": ChunkContentType.PROSE,
        }.get(value, ChunkContentType.MIXED)
    return ChunkContentType.MIXED


def _make_chunk(
    page_index: int,
    sequence_number: int,
    blocks: list[ExtractedBlock],
    section_path: tuple[str, ...],
) -> ExtractedChunk:
    display_text = "\n\n".join(block.text for block in blocks).strip()
    context = " > ".join(section_path)
    embedding_text = f"{context}\n\n{display_text}" if context else display_text
    return ExtractedChunk(
        page_index=page_index,
        sequence_number=sequence_number,
        display_text=display_text,
        embedding_text=embedding_text,
        chapter_title=section_path[0] if section_path else None,
        section_path=section_path,
        content_type=_content_type(blocks),
        token_count=token_count(embedding_text),
        content_sha256=hashlib.sha256(display_text.encode()).hexdigest(),
        provenance={
            "blocks": [
                {
                    "bbox": block.bbox,
                    "char_span": None if block.char_span is None else list(block.char_span),
                    "content_type": block.content_type,
                }
                for block in blocks
            ]
        },
    )


def _flush_chunk(
    chunks: list[ExtractedChunk],
    page_index: int,
    sequence_number: int,
    pending: list[ExtractedBlock],
    section_path: list[str],
) -> int:
    if not pending:
        return sequence_number
    chunks.append(_make_chunk(page_index, sequence_number, pending, tuple(section_path)))
    pending.clear()
    return sequence_number + 1


def chunk_pages(
    pages: tuple[ExtractedPage, ...], *, max_tokens: int = 400
) -> tuple[ExtractedChunk, ...]:
    """Chunk each page at structural boundaries while retaining document heading context."""
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")
    chunks: list[ExtractedChunk] = []
    sequence_number = 0
    section_path: list[str] = []
    for page in pages:
        pending: list[ExtractedBlock] = []

        for block in page.blocks:
            if block.content_type == "heading":
                sequence_number = _flush_chunk(
                    chunks, page.pdf_page_index, sequence_number, pending, section_path
                )
                if block.text in section_path:
                    section_path[:] = section_path[: section_path.index(block.text) + 1]
                else:
                    section_path.append(block.text)
                pending.append(block)
                continue
            candidate = [*pending, block]
            if pending and token_count("\n\n".join(item.text for item in candidate)) > max_tokens:
                sequence_number = _flush_chunk(
                    chunks, page.pdf_page_index, sequence_number, pending, section_path
                )
            if token_count(block.text) <= max_tokens:
                pending.append(block)
                continue
            words = block.text.split()
            fragment: list[str] = []
            for word in words:
                if fragment and token_count(" ".join([*fragment, word])) > max_tokens:
                    pending.append(
                        ExtractedBlock(
                            text=" ".join(fragment),
                            content_type=block.content_type,
                            page_index=block.page_index,
                            bbox=block.bbox,
                            char_span=block.char_span,
                        )
                    )
                    sequence_number = _flush_chunk(
                        chunks, page.pdf_page_index, sequence_number, pending, section_path
                    )
                    fragment.clear()
                fragment.append(word)
            if fragment:
                pending.append(
                    ExtractedBlock(
                        text=" ".join(fragment),
                        content_type=block.content_type,
                        page_index=block.page_index,
                        bbox=block.bbox,
                        char_span=block.char_span,
                    )
                )
        sequence_number = _flush_chunk(
            chunks, page.pdf_page_index, sequence_number, pending, section_path
        )
    return tuple(chunks)

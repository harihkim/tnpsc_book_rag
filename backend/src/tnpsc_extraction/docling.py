"""Docling adapter that preserves page, structure, and picture provenance."""

import hashlib
import json
import re
import unicodedata
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from tnpsc_extraction.models import (
    ExtractedAsset,
    ExtractedBlock,
    ExtractedPage,
    ExtractionBundle,
    ExtractionError,
)

_WHITESPACE = re.compile(r"[ \t]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def normalize_text(value: str) -> str:
    """Normalize retrieval text without changing the lossless raw page text."""
    normalized = unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))
    lines = [_WHITESPACE.sub(" ", line).strip() for line in normalized.split("\n")]
    return _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


def _json_value(value: Any) -> Any:
    """Convert Docling/Pydantic values into JSON-safe primitive values."""
    if hasattr(value, "value") and isinstance(value.value, str):
        return value.value
    if hasattr(value, "model_dump"):
        return _json_value(value.model_dump())
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _provenance(
    item: Any, page_index: int
) -> tuple[dict[str, object] | None, tuple[int, int] | None]:
    for provenance in getattr(item, "prov", ()):
        if int(provenance.page_no) - 1 != page_index:
            continue
        bbox = _json_value(provenance.bbox)
        return (
            bbox if isinstance(bbox, dict) else None,
            tuple(provenance.charspan) if provenance.charspan is not None else None,
        )
    return None, None


def _item_text(item: Any, document: Any) -> str:
    label = str(getattr(getattr(item, "label", None), "value", ""))
    if label == "table" and hasattr(item, "export_to_markdown"):
        return str(item.export_to_markdown(document))
    text = getattr(item, "text", None)
    return text if isinstance(text, str) else ""


def _content_type(item: Any) -> str | None:
    label = str(getattr(getattr(item, "label", None), "value", ""))
    return {
        "section_header": "heading",
        "list_item": "list",
        "table": "table",
        "caption": "caption",
        "text": "prose",
        "formula": "prose",
        "code": "prose",
    }.get(label)


def _caption_text(picture: Any, text_by_ref: dict[str, str]) -> str | None:
    values = [text_by_ref.get(str(reference.cref), "") for reference in picture.captions]
    caption = normalize_text(" ".join(value for value in values if value))
    return caption or None


def _docling_version() -> str:
    try:
        return version("docling")
    except PackageNotFoundError:
        return "unknown"


class DoclingExtractor:
    """Run the standard digital-PDF pipeline with OCR and vision disabled."""

    def __init__(
        self,
        *,
        do_table_structure: bool = True,
        generate_picture_images: bool = True,
        max_tokens: int = 400,
        accelerator_device: str = "auto",
    ) -> None:
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        if accelerator_device not in {"auto", "cpu", "cuda"}:
            raise ValueError("accelerator_device must be auto, cpu, or cuda")
        self.do_table_structure = do_table_structure
        self.generate_picture_images = generate_picture_images
        self.max_tokens = max_tokens
        self.accelerator_device = accelerator_device

    @property
    def config_fingerprint(self) -> str:
        """Identify extraction settings for reproducible re-ingestion."""
        payload = {
            "do_ocr": False,
            "do_picture_classification": False,
            "do_picture_description": False,
            "do_table_structure": self.do_table_structure,
            "accelerator_device": self.accelerator_device,
            "force_backend_text": True,
            "generate_page_images": False,
            "generate_picture_images": self.generate_picture_images,
            "max_tokens": self.max_tokens,
            "pipeline": "standard_pdf",
        }
        return hashlib.sha256(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()

    def extract(self, source: Path, output_dir: Path) -> ExtractionBundle:
        """Convert one complete PDF and write an embedded lossless Docling JSON artifact."""
        from docling.datamodel.accelerator_options import AcceleratorOptions
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling_core.types.doc import ImageRefMode

        if not source.is_file():
            raise ExtractionError("source_not_found", "source PDF does not exist")
        output_dir.mkdir(mode=0o750, parents=True, exist_ok=True)
        options = PdfPipelineOptions(
            accelerator_options=AcceleratorOptions(device=self.accelerator_device),
            do_ocr=False,
            do_picture_classification=False,
            do_picture_description=False,
            do_table_structure=self.do_table_structure,
            force_backend_text=True,
            generate_page_images=False,
            generate_picture_images=self.generate_picture_images,
        )
        converter = DocumentConverter(
            allowed_formats=[InputFormat.PDF],
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)},
        )
        try:
            result = converter.convert(source)
        except Exception as error:
            raise ExtractionError("extraction_failed", "Docling conversion failed") from error
        if result.document is None or not result.document.pages:
            raise ExtractionError("unsupported_document", "PDF did not produce document pages")

        document = result.document
        pages = self._pages(document)
        if not any(page.normalized_text for page in pages):
            raise ExtractionError("unsupported_document", "PDF has no usable text layer")
        assets = self._assets(document, output_dir)
        docling_json_path = output_dir / "docling.json"
        document.save_as_json(docling_json_path, image_mode=ImageRefMode.EMBEDDED)
        return ExtractionBundle(
            pages=tuple(pages),
            assets=tuple(assets),
            docling_json_path=docling_json_path,
            page_count=max(document.pages),
            docling_version=_docling_version(),
            config_fingerprint=self.config_fingerprint,
        )

    def _pages(self, document: Any) -> list[ExtractedPage]:
        pages: list[ExtractedPage] = []
        for page_no, page in sorted(document.pages.items()):
            page_index = int(page_no) - 1
            blocks: list[ExtractedBlock] = []
            for item, level in document.iterate_items(page_no=int(page_no)):
                content_type = _content_type(item)
                if content_type is None:
                    continue
                text = normalize_text(_item_text(item, document))
                if not text:
                    continue
                bbox, char_span = _provenance(item, page_index)
                blocks.append(
                    ExtractedBlock(
                        text=text,
                        content_type=content_type,
                        page_index=page_index,
                        bbox=bbox,
                        char_span=char_span,
                        heading_level=int(level) if content_type == "heading" else None,
                    )
                )
            raw_text = "\n\n".join(block.text for block in blocks)
            warnings: list[dict[str, object]] = []
            if not normalize_text(raw_text):
                warnings.append({"code": "empty_text_layer", "message": "page has no text"})
            pages.append(
                ExtractedPage(
                    pdf_page_index=page_index,
                    width=float(page.size.width) if page.size is not None else None,
                    height=float(page.size.height) if page.size is not None else None,
                    raw_text=raw_text,
                    normalized_text=normalize_text(raw_text),
                    blocks=tuple(blocks),
                    warnings=tuple(warnings),
                )
            )
        return pages

    def _assets(self, document: Any, output_dir: Path) -> list[ExtractedAsset]:
        text_by_ref = {
            str(item.self_ref): _item_text(item, document)
            for item in getattr(document, "texts", ())
            if getattr(item, "self_ref", None)
        }
        assets_dir = output_dir / "images"
        assets_dir.mkdir(mode=0o750, exist_ok=True)
        assets: list[ExtractedAsset] = []
        for ordinal, picture in enumerate(document.pictures):
            provenance = next(iter(getattr(picture, "prov", ())), None)
            if provenance is None:
                continue
            image = picture.get_image(document)
            if image is None:
                continue
            path = assets_dir / f"picture_{ordinal:06d}.png"
            image.save(path, format="PNG")
            bbox = _json_value(provenance.bbox)
            bbox_value = bbox if isinstance(bbox, dict) else None
            origin = None
            if bbox_value is not None and isinstance(bbox_value.get("coord_origin"), str):
                origin = bbox_value["coord_origin"]
            assets.append(
                ExtractedAsset(
                    ordinal=ordinal,
                    page_index=int(provenance.page_no) - 1,
                    path=path,
                    media_type="image/png",
                    width=int(image.width),
                    height=int(image.height),
                    caption=_caption_text(picture, text_by_ref),
                    bounding_box=bbox_value,
                    coordinate_origin=origin,
                    source_reference=str(picture.self_ref),
                    provenance={
                        "self_ref": str(picture.self_ref),
                        "char_span": (
                            None if provenance.charspan is None else list(provenance.charspan)
                        ),
                    },
                )
            )
        return assets

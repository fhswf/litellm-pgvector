from pathlib import Path

from docling.chunking import HybridChunker
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
from docling.document_converter import DocumentConverter
from docling.document_converter import PdfFormatOption
from docling.models.stages.ocr.rapid_ocr_model import RapidOcrModel
from docling_core.transforms.chunker.doc_chunk import DocChunk
from docling_core.transforms.chunker.hierarchical_chunker import (
    ChunkingDocSerializer,
    ChunkingSerializerProvider,
)
from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
from docling_core.transforms.serializer.base import BaseDocSerializer
from docling_core.transforms.serializer.markdown import MarkdownTableSerializer
from docling_core.types.doc.document import (
    DoclingDocument,
    SectionHeaderItem,
    TitleItem,
)


class _MarkdownChunkingDocSerializer(ChunkingDocSerializer):
    # Keep table data as Markdown; Docling's default chunking serializer turns
    # tables into triplets, which is useful for retrieval but loses the source
    # Markdown table structure.
    table_serializer: MarkdownTableSerializer = MarkdownTableSerializer()


class _MarkdownChunkingSerializerProvider(ChunkingSerializerProvider):
    def get_serializer(self, doc: DoclingDocument) -> _MarkdownChunkingDocSerializer:
        return _MarkdownChunkingDocSerializer(doc=doc)


class _MarkdownHybridChunker(HybridChunker):
    def _split_using_plain_text(
        self,
        doc_chunk: DocChunk,
        doc_serializer: BaseDocSerializer,
    ) -> list[DocChunk]:
        # Docling has already identified semantic item boundaries. Splitting
        # serialized text can cut through Markdown links, emphasis, tables, or
        # code blocks, so keep each item intact even when it exceeds the target.
        return [doc_chunk]


class Document():
    _chunks: list = []
    _document: DoclingDocument

    def __init__(self, filepath: str):
        # RapidOCR otherwise writes model weights into its installed package
        # directory, which is read-only in the Kubernetes deployment.
        model_cache_dir = Path.home() / ".cache" / "docling"
        rapidocr_model_dir = model_cache_dir / "RapidOcr"
        is_pdf = Path(filepath).suffix.lower() == ".pdf"
        if not is_pdf:
            with open(filepath, "rb") as source:
                is_pdf = b"%PDF-" in source.read(1024)
        if is_pdf:
            rapidocr_model_dir.mkdir(parents=True, exist_ok=True)
            RapidOcrModel.download_models(
                backend="torch",
                local_dir=rapidocr_model_dir,
                lang="ch",
            )
        # RapidOCR does not use Global.model_root_dir for its character
        # dictionary; without this path it falls back to site-packages/models.
        rapidocr_dict_path = rapidocr_model_dir / "ppocrv6_dict.txt"
        # Leave PdfPipelineOptions.artifacts_path unset. Setting it makes
        # Docling treat the directory as a complete, offline model bundle. The
        # cache here only contains RapidOCR, so layout and table models would
        # fail to initialize instead of being downloaded to Docling's cache.
        pdf_options = PdfPipelineOptions(
            ocr_options=RapidOcrOptions(
                backend="torch",
                lang=["ch"],
                rec_keys_path=str(rapidocr_dict_path),
                rapidocr_params={
                    "Global.model_root_dir": rapidocr_model_dir,
                },
            )
        )
        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_options),
            }
        )
        result = converter.convert(filepath)
        self._document = result.document
        self.title = self._extract_title(filepath)

    def _extract_title(self, filepath: str) -> str | None:
        if Path(filepath).suffix.lower() in {".docx", ".docm"}:
            try:
                from docx import Document as WordDocument

                title = WordDocument(filepath).core_properties.title
                if title and title.strip():
                    return title.strip()
            except Exception:
                # Title is optional metadata and must not affect parsing.
                pass

        for item in self._document.texts:
            if getattr(item, "label", None) == "title":
                title = item.text.strip()
                if title:
                    return title
        return None

    def compute_chunks(
        self,
        max_chunk_size_tokens: int = 800,
        chunk_overlap_tokens: int = 0,
    ) -> list[str]:
        # Retain the overlap argument for callers using the existing strategy
        # shape. Docling's semantic chunker has no fixed-overlap setting.
        _ = chunk_overlap_tokens
        tokenizer = HuggingFaceTokenizer.from_pretrained(
            model_name="sentence-transformers/all-MiniLM-L6-v2",
            max_tokens=max_chunk_size_tokens,
        )
        chunker = _MarkdownHybridChunker(
            tokenizer=tokenizer,
            serializer_provider=_MarkdownChunkingSerializerProvider(),
            delim="\n\n",
        )
        heading_paths = self._heading_paths_by_item_ref()
        chunks = []
        for chunk in chunker.chunk(self._document):
            heading_path: list[tuple[str, int]] = []
            if chunk.meta.doc_items:
                heading_path = heading_paths.get(
                    chunk.meta.doc_items[0].self_ref, []
                )
            heading_markdown = "\n\n".join(
                f"{'#' * level} {text}" for text, level in heading_path
            )
            text = "\n\n".join(
                part for part in (heading_markdown, chunk.text.strip()) if part
            )
            if text:
                chunks.append(text)
        return chunks

    def _heading_paths_by_item_ref(self) -> dict[str, list[tuple[str, int]]]:
        active_headings: dict[int, tuple[str, int]] = {}
        heading_paths: dict[str, list[tuple[str, int]]] = {}
        for item, _ in self._document.iterate_items(with_groups=True):
            if isinstance(item, TitleItem | SectionHeaderItem):
                level = item.level if isinstance(item, SectionHeaderItem) else 0
                for previous_level in list(active_headings):
                    if previous_level >= level:
                        del active_headings[previous_level]
                active_headings[level] = (item.text, max(level, 1))
            elif self_ref := getattr(item, "self_ref", None):
                heading_paths[self_ref] = [
                    active_headings[level] for level in sorted(active_headings)
                ]
        return heading_paths

from pathlib import Path

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
from docling.document_converter import DocumentConverter
from docling.document_converter import PdfFormatOption
from docling.models.stages.ocr.rapid_ocr_model import RapidOcrModel
from docling_core.types.doc.document import DoclingDocument
from transformers import AutoTokenizer

class Document():
    _chunks: list = []
    _document: DoclingDocument

    def __init__(self, filepath: str):
        # RapidOCR otherwise writes model weights into its installed package
        # directory, which is read-only in the Kubernetes deployment.
        artifacts_path = Path.home() / ".cache" / "docling"
        rapidocr_model_dir = artifacts_path / "RapidOcr"
        is_pdf = Path(filepath).suffix.lower() == ".pdf"
        if not is_pdf:
            with open(filepath, "rb") as source:
                is_pdf = b"%PDF-" in source.read(1024)
        if is_pdf:
            rapidocr_model_dir.mkdir(parents=True, exist_ok=True)
            # Docling's artifacts directory also controls the recognition-key
            # dictionary path. RapidOCR otherwise downloads that file to its
            # package's models directory, even when model_root_dir is configured.
            RapidOcrModel.download_models(
                backend="torch",
                local_dir=rapidocr_model_dir,
                lang="chinese",
            )
        pdf_options = PdfPipelineOptions(
            artifacts_path=artifacts_path,
            ocr_options=RapidOcrOptions(
                backend="torch",
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
        chunk_overlap_tokens: int = 400,
    ) -> list[str]:
        tokenizer = AutoTokenizer.from_pretrained(
            "sentence-transformers/all-MiniLM-L6-v2", use_fast=True
        )
        markdown = self._document.export_to_markdown()
        encoded = tokenizer(
            markdown,
            add_special_tokens=False,
            return_offsets_mapping=True,
            truncation=False,
        )
        tokens = encoded["input_ids"]
        offsets = encoded["offset_mapping"]
        token_text = tokenizer.convert_ids_to_tokens(tokens)
        step = max_chunk_size_tokens - chunk_overlap_tokens
        chunks = []
        for start in range(0, len(tokens), step):
            end = min(start + max_chunk_size_tokens, len(tokens))

            # Use tokenizer offsets to slice the original Markdown. Decoding
            # WordPiece tokens inserts spaces around punctuation such as '*',
            # '_', '&', and '-', which changes Markdown and document text.
            # If a boundary falls inside a WordPiece word, include its adjacent
            # pieces so a chunk does not start or end in the middle of a word.
            span_start = start
            while span_start > 0 and token_text[span_start].startswith("##"):
                span_start -= 1
            span_end = end
            while span_end < len(tokens) and token_text[span_end].startswith("##"):
                span_end += 1

            char_start = offsets[span_start][0]
            char_end = offsets[span_end - 1][1]
            chunk = markdown[char_start:char_end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(tokens):
                break
        return chunks

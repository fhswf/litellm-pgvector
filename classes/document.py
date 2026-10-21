from pathlib import Path

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
from docling.document_converter import DocumentConverter
from docling.document_converter import PdfFormatOption
from docling_core.types.doc.document import DoclingDocument
from transformers import AutoTokenizer

class Document():
    _chunks: list = []
    _document: DoclingDocument

    def __init__(self, filepath: str):
        # RapidOCR otherwise writes model weights into its installed package
        # directory, which is read-only in the Kubernetes deployment.
        rapidocr_model_dir = Path.home() / ".cache" / "rapidocr" / "models"
        rapidocr_model_dir.mkdir(parents=True, exist_ok=True)
        pdf_options = PdfPipelineOptions(
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

    def compute_chunks(
        self,
        max_chunk_size_tokens: int = 800,
        chunk_overlap_tokens: int = 400,
    ) -> list[str]:
        tokenizer = AutoTokenizer.from_pretrained("sentence-transformers/all-MiniLM-L6-v2")
        tokens = tokenizer.encode(self._document.export_to_markdown(), add_special_tokens=False)
        step = max_chunk_size_tokens - chunk_overlap_tokens
        chunks = []
        for start in range(0, len(tokens), step):
            chunk = tokenizer.decode(
                tokens[start : start + max_chunk_size_tokens], skip_special_tokens=True
            ).strip()
            if chunk:
                chunks.append(chunk)
            if start + max_chunk_size_tokens >= len(tokens):
                break
        return chunks

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

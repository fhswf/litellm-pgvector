from docling.document_converter import DocumentConverter
from docling_core.types.doc.document import DoclingDocument
from transformers import AutoTokenizer

class Document():
    _chunks: list = []
    _document: DoclingDocument

    def __init__(self, filepath: str):
        converter = DocumentConverter()
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

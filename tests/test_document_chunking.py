"""Unit tests for document model caching and semantic Markdown chunking."""

from pathlib import Path
import re
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from docling.datamodel.base_models import InputFormat
from docling_core.transforms.chunker.tokenizer.base import BaseTokenizer
from docling_core.types.doc.common.formatting import Formatting
from docling_core.types.doc.common.reference import RefItem
from docling_core.types.doc.document import (
    CodeItem,
    DoclingDocument,
    SectionHeaderItem,
    TableItem,
    TextItem,
    TitleItem,
)
from docling_core.types.doc.items.group import GroupItem
from docling_core.types.doc.items.table.table_data import TableCell, TableData
from docling_core.types.doc.labels import CodeLanguageLabel, DocItemLabel

from classes import document as document_module
from classes.document import Document


class WhitespaceTokenizer(BaseTokenizer):
    max_tokens: int = 100

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def get_max_tokens(self) -> int:
        return self.max_tokens

    def get_tokenizer(self):
        return self


class DocumentModelCacheTests(unittest.TestCase):
    def test_pdf_models_use_writable_cache_and_not_offline_artifacts_path(self):
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            home = root / "home"
            home.mkdir()
            pdf_path = root / "sample.pdf"
            pdf_path.write_bytes(b"%PDF-1.7\n")
            readonly_package_models = root / "site-packages" / "rapidocr" / "models"
            readonly_package_models.mkdir(parents=True)
            readonly_package_models.chmod(0o555)

            try:
                expected_model_dir = home / ".cache" / "docling" / "RapidOcr"

                def download_models(**kwargs):
                    local_dir = Path(kwargs["local_dir"])
                    self.assertEqual(local_dir, expected_model_dir)
                    self.assertNotEqual(local_dir, readonly_package_models)
                    local_dir.mkdir(parents=True, exist_ok=True)
                    (local_dir / "downloaded-model.marker").write_text("cached")

                converter = Mock()
                converter.convert.return_value = SimpleNamespace(
                    document=SimpleNamespace(texts=[])
                )
                with (
                    patch.object(Path, "home", return_value=home),
                    patch.object(
                        document_module.RapidOcrModel,
                        "download_models",
                        side_effect=download_models,
                    ),
                    patch.object(
                        document_module,
                        "DocumentConverter",
                        return_value=converter,
                    ) as converter_factory,
                ):
                    Document(str(pdf_path))

                converter_factory.assert_called_once()
                pdf_options = converter_factory.call_args.kwargs["format_options"][
                    InputFormat.PDF
                ].pipeline_options
                self.assertIsNone(pdf_options.artifacts_path)
                self.assertEqual(
                    pdf_options.ocr_options.rapidocr_params[
                        "Global.model_root_dir"
                    ],
                    expected_model_dir,
                )
                self.assertTrue(
                    (expected_model_dir / "downloaded-model.marker").is_file()
                )
                self.assertEqual(list(readonly_package_models.iterdir()), [])
            finally:
                readonly_package_models.chmod(0o755)


class SemanticMarkdownChunkingTests(unittest.TestCase):
    def test_chunks_keep_markdown_headings_formatting_links_tables_and_code(self):
        body_ref = RefItem(cref="#/body")
        title = TitleItem(
            self_ref="#/texts/0",
            parent=body_ref,
            orig="Guide",
            text="Guide",
        )
        section = SectionHeaderItem(
            self_ref="#/texts/1",
            parent=body_ref,
            orig="Formatting",
            text="Formatting",
            level=2,
        )
        formatted = TextItem(
            self_ref="#/texts/2",
            parent=body_ref,
            label=DocItemLabel.PARAGRAPH,
            orig="bold text",
            text="bold text",
            formatting=Formatting(bold=True),
        )
        linked = TextItem(
            self_ref="#/texts/3",
            parent=body_ref,
            label=DocItemLabel.PARAGRAPH,
            orig="reference",
            text="reference",
            hyperlink="https://example.com/guide",
        )
        table = TableItem(
            self_ref="#/tables/0",
            parent=body_ref,
            data=TableData(
                num_rows=2,
                num_cols=2,
                table_cells=[
                    TableCell(
                        start_row_offset_idx=0,
                        end_row_offset_idx=1,
                        start_col_offset_idx=0,
                        end_col_offset_idx=1,
                        text="Name",
                        column_header=True,
                    ),
                    TableCell(
                        start_row_offset_idx=0,
                        end_row_offset_idx=1,
                        start_col_offset_idx=1,
                        end_col_offset_idx=2,
                        text="Value",
                        column_header=True,
                    ),
                    TableCell(
                        start_row_offset_idx=1,
                        end_row_offset_idx=2,
                        start_col_offset_idx=0,
                        end_col_offset_idx=1,
                        text="item",
                    ),
                    TableCell(
                        start_row_offset_idx=1,
                        end_row_offset_idx=2,
                        start_col_offset_idx=1,
                        end_col_offset_idx=2,
                        text="preserved",
                    ),
                ],
            ),
        )
        code = CodeItem(
            self_ref="#/texts/4",
            parent=body_ref,
            orig='print("markdown-safe")',
            text='print("markdown-safe")',
            code_language=CodeLanguageLabel.PYTHON,
        )
        doc = DoclingDocument(
            name="markdown-sample",
            body=GroupItem(
                self_ref="#/body",
                name="_root_",
                children=[
                    RefItem(cref=title.self_ref),
                    RefItem(cref=section.self_ref),
                    RefItem(cref=formatted.self_ref),
                    RefItem(cref=linked.self_ref),
                    RefItem(cref=table.self_ref),
                    RefItem(cref=code.self_ref),
                ],
            ),
            texts=[title, section, formatted, linked, code],
            tables=[table],
        )
        document = Document.__new__(Document)
        document._document = doc

        with patch.object(
            document_module.HuggingFaceTokenizer,
            "from_pretrained",
            side_effect=lambda **kwargs: WhitespaceTokenizer(
                max_tokens=kwargs["max_tokens"]
            ),
        ):
            chunks = document.compute_chunks(max_chunk_size_tokens=3)

        markdown = "\n\n".join(chunks)
        self.assertGreater(len(chunks), 1)
        self.assertIn("# Guide", markdown)
        self.assertIn("## Formatting", markdown)
        self.assertTrue(any("**bold text**" in chunk for chunk in chunks))
        self.assertTrue(
            any("[reference](https://example.com/guide)" in chunk for chunk in chunks)
        )

        table_chunk = next(
            chunk
            for chunk in chunks
            if re.search(r"\|\s*Name\s*\|\s*Value\s*\|", chunk)
        )
        self.assertRegex(table_chunk, r"\|\s*item\s*\|\s*preserved\s*\|")

        code_chunk = next(chunk for chunk in chunks if 'print("markdown-safe")' in chunk)
        self.assertEqual(code_chunk.count("```"), 2)


if __name__ == "__main__":
    unittest.main()

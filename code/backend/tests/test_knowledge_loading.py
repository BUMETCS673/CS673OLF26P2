"""Loading uploaded files, and splitting them into chunks."""

import io

import pytest
from langchain_core.documents import Document
from pypdf import PdfWriter

from app.ai.knowledge.loaders import PDF, TEXT_PAGE_SIZE, UnreadableDocument, loader_for
from app.ai.knowledge.splitting import CHUNK_SIZE, split_pages


def _pdf(*page_texts):
    """A small valid PDF with one page per text. An empty text makes a page with no text layer."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        None,  # the page list, once the page numbers are known
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    kids = []
    for text in page_texts:
        content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode() if text else b""
        kids.append(f"{len(objects) + 1} 0 R")
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {len(objects) + 2} 0 R"
            " /Resources << /Font << /F1 3 0 R >> >> >>".encode()
        )
        objects.append(
            f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream"
        )
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>".encode()

    out = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{offset:010} 00000 n \n" for offset in offsets).encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode()
    return out + f"startxref\n{xref}\n%%EOF\n".encode()


@pytest.fixture
def loader(tmp_path):
    def _loader(data: bytes, mime_type: str):
        path = tmp_path / "upload"
        path.write_bytes(data)
        return loader_for(mime_type, str(path))

    return _loader


# --- PDF ----------------------------------------------------------------------------------


def test_a_pdf_gives_each_pages_number_and_text(loader):
    pages = list(loader(_pdf("Cells divide", "ATP stores energy"), PDF).lazy_load())

    assert [page.metadata["page"] for page in pages] == [1, 2]
    assert "Cells divide" in pages[0].page_content
    assert "ATP stores energy" in pages[1].page_content


def test_a_page_with_no_text_layer_is_empty_but_still_counted(loader):
    pages = list(loader(_pdf("Cells divide", ""), PDF).lazy_load())

    assert pages[1].metadata["page"] == 2
    assert pages[1].page_content.strip() == ""


def test_a_corrupt_pdf_is_unreadable(loader):
    with pytest.raises(UnreadableDocument):
        list(loader(b"%PDF-1.7\nnot really a pdf", PDF).lazy_load())


def test_a_pdf_outline_gives_its_top_level_titles(loader):
    writer = PdfWriter()
    writer.add_blank_page(200, 200)
    cells = writer.add_outline_item("Cells", 0)
    writer.add_outline_item("Prophase", 0, parent=cells)
    writer.add_outline_item("Enzymes", 0)
    output = io.BytesIO()
    writer.write(output)

    assert loader(output.getvalue(), PDF).headings() == ["Cells", "Enzymes"]


def test_a_pdf_with_no_outline_has_no_headings(loader):
    assert loader(_pdf("Cells"), PDF).headings() == []


def test_a_corrupt_pdf_has_no_headings_rather_than_an_error(loader):
    assert loader(b"%PDF-1.7\nnot really a pdf", PDF).headings() == []


# --- text ---------------------------------------------------------------------------------


@pytest.mark.parametrize("mime_type", ["text/plain", "text/markdown"])
def test_a_short_text_file_is_one_page_with_no_number(loader, mime_type):
    [page] = loader(b"Cells divide\n", mime_type).lazy_load()

    assert page.page_content == "Cells divide\n"
    assert page.metadata["page"] is None


def test_a_byte_order_mark_isnt_part_of_the_text(loader):
    [page] = loader(b"\xef\xbb\xbfCells", "text/plain").lazy_load()

    assert page.page_content == "Cells"


def test_a_long_text_file_is_read_in_pieces_without_losing_any(loader):
    text = "Cells divide\n" * (TEXT_PAGE_SIZE // 5)

    pages = list(loader(text.encode(), "text/plain").lazy_load())

    assert len(pages) > 1
    assert "".join(page.page_content for page in pages) == text


def test_a_text_file_that_isnt_utf8_is_unreadable(loader):
    with pytest.raises(UnreadableDocument):
        list(loader(b"caf\xe9", "text/plain").lazy_load())


def test_an_empty_text_file_has_no_pages(loader):
    assert list(loader(b"", "text/plain").lazy_load()) == []


def test_markdown_headings_skip_deep_levels_and_code(loader):
    data = b"# Cells\ntext\n## Mitosis ##\n### Prophase\n```\n# a comment\n```\n#notaheading\n"

    assert loader(data, "text/markdown").headings() == ["Cells", "Mitosis"]


def test_a_plain_text_file_has_no_headings(loader):
    assert loader(b"# Cells\n", "text/plain").headings() == []


def test_an_unsupported_type_has_no_loader(loader):
    assert loader(b"x", "image/png") is None


# --- splitting ----------------------------------------------------------------------------


def _page(text, number=1):
    return Document(page_content=text, metadata={"page": number})


def test_a_short_page_is_one_chunk():
    [chunk] = split_pages([_page("Cells divide.", 3)])

    assert chunk.page_content == "Cells divide."
    assert (chunk.metadata["page"], chunk.metadata["chunk_index"]) == (3, 0)


def test_a_long_page_is_split_to_size_and_keeps_its_number():
    chunks = split_pages([_page("Cells divide often. " * 500)])

    assert len(chunks) > 1
    assert all(len(chunk.page_content) <= CHUNK_SIZE for chunk in chunks)
    assert {chunk.metadata["page"] for chunk in chunks} == {1}


def test_indexes_run_across_pages_and_skip_blank_ones():
    chunks = split_pages([_page("Cells.", 1), _page("   ", 2), _page("ATP.", 3)])

    assert [(chunk.metadata["chunk_index"], chunk.metadata["page"]) for chunk in chunks] == [
        (0, 1),
        (1, 3),
    ]


def test_the_same_pages_get_the_same_chunks():
    pages = [_page("Cells divide often. " * 500), _page("ATP stores energy.", 2)]

    first = [(chunk.page_content, chunk.metadata) for chunk in split_pages(pages)]
    second = [(chunk.page_content, chunk.metadata) for chunk in split_pages(pages)]

    assert first == second

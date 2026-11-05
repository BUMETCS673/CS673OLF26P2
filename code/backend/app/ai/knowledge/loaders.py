"""Loading uploaded files a page at a time, as LangChain Documents."""

import re
from collections.abc import Iterator

from langchain_core.document_loaders import BaseLoader
from langchain_core.documents import Document
from pypdf import PdfReader
from pypdf.errors import PyPdfError

PDF = "application/pdf"
TEXT_PAGE_SIZE = 100_000  # characters. Text files have no pages, so they're read in pieces.

# Uploads are untrusted, and a malformed PDF can raise more than pypdf's own errors.
_PDF_FAILURES = (PyPdfError, ValueError, KeyError, TypeError, AttributeError, IndexError)

_MARKDOWN_HEADING = re.compile(r"^#{1,2}\s+(.+?)\s*#*\s*$")  # level 1 and 2 headings only


class UnreadableDocument(Exception):
    """The file is corrupt, password-protected, or not in its stated format."""


class HeadingLoader(BaseLoader):
    """A loader that can also list a file's top-level headings, if its format has them."""

    def __init__(self, path: str):
        self.path = path

    def headings(self) -> list[str]:
        """Never raises for a bad file, since headings are only used for suggestions."""
        return []


class PdfLoader(HeadingLoader):
    def lazy_load(self) -> Iterator[Document]:
        """One Document per page, including empty ones, such as scans, to keep the numbering."""
        with open(self.path, "rb") as file:  # given a path, pypdf would load the whole file
            try:
                # pages are read one at a time as the caller asks for them
                for number, page in enumerate(PdfReader(file).pages, start=1):
                    text = page.extract_text() or ""  # None for a page with no text layer
                    yield Document(page_content=text, metadata={"page": number})  # 1-based
            except _PDF_FAILURES:
                raise UnreadableDocument() from None  # one clear error for the job to report

    def headings(self) -> list[str]:
        with open(self.path, "rb") as file:
            try:
                # A nested list holds an item's children, which aren't top-level.
                return [
                    item.title
                    for item in PdfReader(file).outline
                    if not isinstance(item, list) and item.title
                ]
            except _PDF_FAILURES:
                return []  # no headings just means the model suggests topics instead


class TextLoader(HeadingLoader):
    def lazy_load(self) -> Iterator[Document]:
        lines, size = [], 0  # one page's worth of lines and its length so far
        try:
            with open(self.path, encoding="utf-8-sig") as file:  # a byte-order mark isn't text
                for line in file:  # streams the file instead of reading it all at once
                    lines.append(line)
                    size += len(line)
                    if size >= TEXT_PAGE_SIZE:  # cut at a line end never mid-line
                        yield Document(page_content="".join(lines), metadata={"page": None})
                        lines, size = [], 0
        except UnicodeDecodeError:  # not UTF-8 so probably not a text file
            raise UnreadableDocument() from None
        if lines:  # the last shorter page
            yield Document(page_content="".join(lines), metadata={"page": None})


class MarkdownLoader(TextLoader):
    def headings(self) -> list[str]:
        headings, in_code_block = [], False
        # errors=replace since a bad byte shouldn't stop heading suggestions
        with open(self.path, encoding="utf-8-sig", errors="replace") as file:
            for line in file:
                if line.lstrip().startswith("```"):
                    in_code_block = not in_code_block  # a "# comment" in code isn't a heading
                elif not in_code_block and (match := _MARKDOWN_HEADING.match(line)):
                    headings.append(match[1])
        return headings


_LOADERS = {PDF: PdfLoader, "text/plain": TextLoader, "text/markdown": MarkdownLoader}


def loader_for(mime_type: str, path: str) -> HeadingLoader | None:
    """The loader for an upload's type, or None if that type isn't supported."""
    loader = _LOADERS.get(mime_type)  # a table lookup instead of an if chain
    return loader(path) if loader else None

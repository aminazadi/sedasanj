"""The minimal Word writer: well-formed XML, escaped text, headings and lists."""

import io
import zipfile
from xml.etree import ElementTree

from app.services import document_docx

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def _document(markdown: str, **kwargs: str) -> ElementTree.Element:
    data = document_docx.render(markdown, **kwargs)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert archive.testzip() is None
        return ElementTree.fromstring(archive.read("word/document.xml"))


def test_headings_bullets_and_numbers_become_styled_rtl_paragraphs() -> None:
    root = _document("# عنوان\n## بخش\n- نکته\n1. اول\nمتن ساده", title="سند")
    paragraphs = root.findall(".//w:p", NS)
    styles = [
        p.find("w:pPr/w:pStyle", NS).get(f"{{{NS['w']}}}val")  # type: ignore[union-attr]
        for p in paragraphs
    ]
    assert styles == ["Heading1", "Heading1", "Heading2", "Normal", "Normal", "Normal"]
    assert all(p.find("w:pPr/w:bidi", NS) is not None for p in paragraphs)
    texts = ["".join(t.text or "" for t in p.findall(".//w:t", NS)) for p in paragraphs]
    assert texts == ["سند", "عنوان", "بخش", "• نکته", "1. اول", "متن ساده"]


def test_markup_and_control_characters_in_the_text_cannot_break_the_file() -> None:
    root = _document("a <script>x</script> & \x00\x0b b")
    text = "".join(t.text or "" for t in root.findall(".//w:t", NS))
    assert "<script>x</script> &" in text and "\x00" not in text


def test_empty_markdown_still_gives_an_openable_file() -> None:
    assert len(_document("").findall(".//w:p", NS)) == 1

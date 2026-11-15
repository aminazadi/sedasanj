"""A minimal right-to-left Word (.docx) file from the simple Markdown the documents use.

Only what the generated documents contain is supported: `#`/`##`/`###` headings, `-`/`*` bullets,
numbered lines and plain paragraphs. The file is built in memory as a zip of XML parts, so no extra
library is needed and nothing from the text can become markup (every run is XML-escaped).
"""

# ruff: noqa: E501 - XML parts are kept as readable single-line literals

from __future__ import annotations

import io
import re
import zipfile
from xml.sax.saxutils import escape

_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '<Override PartName="/word/styles.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
    "</Types>"
)
_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    'Target="word/document.xml"/></Relationships>'
)
_DOC_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
    'Target="styles.xml"/></Relationships>'
)
_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_FONT = '<w:rFonts w:ascii="Tahoma" w:hAnsi="Tahoma" w:cs="Tahoma"/>'
_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    f'<w:styles xmlns:w="{_W}">'
    f'<w:docDefaults><w:rPrDefault><w:rPr>{_FONT}<w:sz w:val="24"/><w:szCs w:val="24"/>'
    '<w:lang w:val="fa-IR" w:bidi="fa-IR"/></w:rPr></w:rPrDefault></w:docDefaults>'
    '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
    '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/>'
    '<w:rPr><w:b/><w:bCs/><w:sz w:val="36"/><w:szCs w:val="36"/></w:rPr></w:style>'
    '<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/>'
    '<w:rPr><w:b/><w:bCs/><w:sz w:val="30"/><w:szCs w:val="30"/></w:rPr></w:style>'
    '<w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/>'
    '<w:rPr><w:b/><w:bCs/><w:sz w:val="26"/><w:szCs w:val="26"/></w:rPr></w:style>'
    "</w:styles>"
)
_HEADING = re.compile(r"^(#{1,3})[ \t]+(.+?)[ \t]*#*$")
_BULLET = re.compile(r"^[-*][ \t]+(.+)$")
_NUMBERED = re.compile(r"^(\d+)[.)][ \t]+(.+)$")
# XML 1.0 forbids most control characters; model output could contain them.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _paragraph(text: str, *, style: str | None = None, indent: bool = False) -> str:
    safe = escape(_CONTROL.sub("", text))
    return (
        f'<w:p><w:pPr><w:pStyle w:val="{style or "Normal"}"/><w:bidi/>'
        + ('<w:ind w:start="360" w:hanging="260"/>' if indent else "")
        + f'</w:pPr><w:r><w:rPr>{_FONT}<w:rtl/></w:rPr><w:t xml:space="preserve">{safe}</w:t></w:r></w:p>'
    )


def render(markdown: str, *, title: str | None = None) -> bytes:
    """The document as .docx bytes; `title` becomes a first heading when given."""
    paragraphs: list[str] = []
    if title:
        paragraphs.append(_paragraph(title, style="Heading1"))
    for raw in markdown.splitlines():
        line = raw.strip()
        if not line:
            continue
        heading = _HEADING.match(line)
        bullet = _BULLET.match(line)
        numbered = _NUMBERED.match(line)
        if heading:
            paragraphs.append(_paragraph(heading.group(2), style=f"Heading{len(heading.group(1))}"))
        elif bullet:
            paragraphs.append(_paragraph("• " + bullet.group(1), indent=True))
        elif numbered:
            paragraphs.append(_paragraph(f"{numbered.group(1)}. {numbered.group(2)}", indent=True))
        else:
            paragraphs.append(_paragraph(line))
    body = "".join(paragraphs) or _paragraph("")
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{_W}"><w:body>{body}'
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134" w:header="708" w:footer="708"/>'
        "<w:bidi/></w:sectPr></w:body></w:document>"
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
        archive.writestr("_rels/.rels", _RELS)
        archive.writestr("word/document.xml", document)
        archive.writestr("word/_rels/document.xml.rels", _DOC_RELS)
        archive.writestr("word/styles.xml", _STYLES)
    return output.getvalue()

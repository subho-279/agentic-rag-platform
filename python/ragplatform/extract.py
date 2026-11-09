"""Text extraction. PDFs go through PyMuPDF (text + detected tables); text formats are read directly."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

TEXT_SUFFIXES = {".txt", ".md", ".csv"}
PDF_SUFFIX = ".pdf"
SUPPORTED_SUFFIXES = TEXT_SUFFIXES | {PDF_SUFFIX}


@dataclass
class Section:
    text: str
    page: int | None = None


def _table_to_markdown(rows: list[list[str | None]]) -> str:
    cleaned = [[(c or "").replace("\n", " ").strip() for c in row] for row in rows if row]
    if not cleaned:
        return ""
    header, *body = cleaned
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join(["---"] * len(header)) + "|"]
    lines += ["| " + " | ".join(r) + " |" for r in body]
    return "\n".join(lines)


def _extract_pdf(path: Path) -> list[Section]:
    import pymupdf as fitz  # PyMuPDF; imported lazily so text-only deployments/tests don't need it

    sections: list[Section] = []
    with fitz.open(path) as doc:
        for number, page in enumerate(doc, start=1):
            parts = [page.get_text("text").strip()]
            try:
                for table in page.find_tables().tables:
                    md = _table_to_markdown(table.extract())
                    if md:
                        parts.append(md)
            except Exception:
                pass  # table detection is best-effort
            text = "\n\n".join(p for p in parts if p)
            if text:
                sections.append(Section(text=text, page=number))
    return sections


def extract_sections(path: str | Path) -> list[Section]:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == PDF_SUFFIX:
        return _extract_pdf(path)
    if suffix in TEXT_SUFFIXES:
        return [Section(text=path.read_text(encoding="utf-8", errors="replace"))]
    raise ValueError(f"unsupported file type: {suffix or '(none)'}")

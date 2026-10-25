import csv
import io
import json
import re
from datetime import datetime
from pathlib import Path

EXPORT_DIR = Path("data/exports")
SUPPORTED_FORMATS = {"txt", "md", "json", "csv", "pdf"}


def detect_export_format(prompt: str) -> str | None:
    text = (prompt or "").lower()
    patterns = [
        ("pdf", r"\b(?:pdf|portable document)\b"),
        ("md", r"\b(?:markdown|\.md)\b"),
        ("json", r"\bjson\b"),
        ("csv", r"\bcsv\b|spreadsheet|lembar kerja"),
        ("txt", r"\b(?:txt|text file|file teks|plain text)\b"),
    ]
    for extension, pattern in patterns:
        if re.search(pattern, text):
            return extension
    if re.search(r"\b(?:buat|buatkan|jadikan|simpan|kirim|download|unduh|export).{0,50}\b(?:file|dokumen|document)\b", text):
        return "txt"
    return None


def should_export(prompt: str, reply: str) -> bool:
    explicit = detect_export_format(prompt) is not None
    return explicit or len(reply or "") > 7000


def _safe_stem(prompt: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", (prompt or "").lower())[:5]
    stem = "_".join(words) or "hanna_ai_document"
    return stem[:48]


def _write_pdf(path: Path, content: str, title: str) -> None:
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Preformatted, SimpleDocTemplate, Spacer
    from xml.sax.saxutils import escape

    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "HannaBody", parent=styles["BodyText"], fontName="Helvetica",
        fontSize=10, leading=14, alignment=TA_LEFT, spaceAfter=6,
    )
    heading = ParagraphStyle(
        "HannaHeading", parent=styles["Heading2"], fontName="Helvetica-Bold",
        fontSize=15, leading=19, spaceBefore=8, spaceAfter=8,
    )
    code_style = ParagraphStyle(
        "HannaCode", parent=styles["Code"], fontName="Courier",
        fontSize=8, leading=10, leftIndent=6, rightIndent=6,
    )
    story = [Paragraph(escape(title), styles["Title"]), Spacer(1, 6)]
    in_code = False
    code_lines: list[str] = []
    for line in content.replace("\r\n", "\n").split("\n"):
        if line.strip().startswith("```"):
            if in_code:
                story.append(Preformatted("\n".join(code_lines), code_style))
                story.append(Spacer(1, 6))
                code_lines = []
            in_code = not in_code
            continue
        if in_code:
            code_lines.append(line)
            continue
        clean = re.sub(r"^\s{0,3}#{1,6}\s+", "", line)
        if re.match(r"^\s{0,3}#{1,6}\s+", line):
            story.append(Paragraph(escape(clean), heading))
        elif clean.strip():
            story.append(Paragraph(escape(clean).replace("\n", "<br/>"), body))
        else:
            story.append(Spacer(1, 4))
    if code_lines:
        story.append(Preformatted("\n".join(code_lines), code_style))
    document = SimpleDocTemplate(
        str(path), pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title=title, author="Hanna AI",
    )
    document.build(story)


def create_export_file(prompt: str, content: str, extension: str | None = None) -> Path:
    extension = extension or detect_export_format(prompt) or "txt"
    if extension not in SUPPORTED_FORMATS:
        extension = "txt"
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = EXPORT_DIR / f"{_safe_stem(prompt)}_{stamp}.{extension}"

    if extension == "pdf":
        _write_pdf(path, content, _safe_stem(prompt).replace("_", " ").title())
    elif extension == "json":
        payload = {"source": "Hanna AI", "prompt": prompt, "content": content, "created_at": datetime.now().isoformat()}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    elif extension == "csv":
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["Hanna AI response"])
            for line in content.splitlines():
                writer.writerow([line])
    else:
        path.write_text(content, encoding="utf-8")
    return path

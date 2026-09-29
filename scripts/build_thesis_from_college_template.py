#!/usr/bin/env python3
"""
Fill the college "Main Project Template.docx" with AI Job Market thesis content.

Steps:
  1) Remove the stray first title page (sample translator project).
  2) Replace CVD sample text in title block, certificate, declaration, acknowledgement,
     and abstract with project-specific strings.
  3) Remove everything from the first body chapter marker through the end of the document
     body (preserves section properties / styles from the template).
  4) Append paragraphs parsed from THESIS_32_PAGES_CONTENT.md.

Usage:
  uv run --with python-docx scripts/build_thesis_from_college_template.py
  uv run --with python-docx scripts/build_thesis_from_college_template.py \\
      --template /path/to/Main\\ Project\\ Template.docx \\
      --markdown THESIS_32_PAGES_CONTENT.md \\
      --output THESIS_COLLEGE_TEMPLATE.docx

Requires: python-docx (not listed in backend pyproject; use uv --with).
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from docx import Document
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT
from docx.shared import Pt

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEMPLATE = ROOT / "templates" / "Main Project Template.docx"
FALLBACK_TEMPLATE = Path.home() / "Downloads" / "Main Project Template.docx"
DEFAULT_MD = ROOT / "THESIS_32_PAGES_CONTENT.md"
DEFAULT_OUT = ROOT / "THESIS_COLLEGE_TEMPLATE.docx"

# Project-specific front matter (edit before binding)
PROJECT_TITLE = (
    "AI JOB MARKET SKILL GAP ANALYZER USING EMBEDDINGS, "
    "SKILL EXTRACTION, AND DEMAND-AWARE SCORING"
)
STUDENT_BLOCK = "B. Sai Vignesh\tRoll No. ____________________"
SUPERVISOR_PRIMARY = "Dr. B. Bhaskara Rao, M. Tech., (Ph.D.)"
SUPERVISOR_PRIMARY_ROLE = "Associate Professor & HOD, Dept. of CSE (DS)"
SUPERVISOR_SECOND = "Ms. R. Arshiya, M. Tech."
SUPERVISOR_SECOND_ROLE = "Assistant Professor, Dept. of CSE(DS)"

CERTIFICATE_TEXT = (
    "This is to certify that B. Sai Vignesh of IV- B. Tech II- Semester, has carried out "
    "the major project work entitled “"
    + PROJECT_TITLE
    + "” under the supervision and guidance of "
    + SUPERVISOR_PRIMARY
    + ", "
    + SUPERVISOR_PRIMARY_ROLE
    + ", and "
    + SUPERVISOR_SECOND
    + ", "
    + SUPERVISOR_SECOND_ROLE
    + ", in the Department of Computer Science and Engineering (Data Science), "
    "Rajeev Gandhi Memorial College of Engineering & Technology (Autonomous), Nandyal, "
    "during the academic year 2025–2026."
)

DECLARATION_TEXT = (
    "I hereby declare that the work done in this project entitled “"
    + PROJECT_TITLE
    + "” submitted towards completion of the major project in IV- Year II- Semester of "
    "B. Tech CSE (Data Science) at the Rajeev Gandhi Memorial College of Engineering & "
    "Technology (Autonomous), Nandyal, is a record of original work done by me under the "
    "supervision of "
    + SUPERVISOR_PRIMARY
    + " and "
    + SUPERVISOR_SECOND
    + ". I have not submitted the matter embodied in this report for the award of any "
    "other degree in any other institution."
)

ACK_TEXT = (
    "I express my sincere gratitude to my project supervisor "
    + SUPERVISOR_PRIMARY
    + " and co-supervisor "
    + SUPERVISOR_SECOND
    + " for their guidance during design, implementation, and deployment of the "
    "AI Job Market Skill Gap Analyzer system. I thank the Head of the Department, the "
    "Principal, and the department staff for their support. I thank my family for encouragement."
)

ABSTRACT_LEAD = (
    "Online job descriptions are skill-dense and synonym-rich. This project implements "
    "a full-stack analyzer that ingests resume PDFs, extracts normalized skills, scrapes "
    "and stores job postings, and reports market fit, gap, matched and missing skills, "
    "and demand-ranked learning priorities using BGE embeddings (BAAI/bge-small-en-v1.5), "
    "a transparent composite match score (semantic, overlap, keyword, demand penalty) with "
    "95% confidence intervals, FastAPI + PostgreSQL, optional Redis/ARQ workers, optional "
    "Ollama advice, and a React + TypeScript dashboard. Demand is defined relative to the "
    "stored posting sample, not national labor statistics."
)


def delete_paragraph(paragraph) -> None:
    el = paragraph._element
    parent = el.getparent()
    if parent is not None:
        parent.remove(el)


def strip_markdown_inline(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\[(.+?)\]\([^)]+\)", r"\1", text)
    return text


def parse_markdown_to_blocks(path: Path) -> list[tuple[str, int]]:
    """
    Return list of (text, level) where level 0=normal, 1=h1, 2=h2, 3=h3.
    Skips horizontal rules and figure-only lines; coalesces soft breaks.
    """
    raw = path.read_text(encoding="utf-8")
    lines = raw.splitlines()
    blocks: list[tuple[str, int]] = []
    buf: list[str] = []
    buf_level = 0

    def flush() -> None:
        nonlocal buf, buf_level
        if buf:
            text = strip_markdown_inline(" ".join(buf)).strip()
            if text:
                blocks.append((text, buf_level))
        buf = []
        buf_level = 0

    for line in lines:
        s = line.strip()
        if not s:
            flush()
            continue
        if s.lower().startswith("*end of manuscript"):
            flush()
            continue
        if s == "---":
            flush()
            continue
        if s.startswith("|") and s.endswith("|"):
            continue
        if re.match(r"^[-*]{3,}$", s):
            flush()
            continue
        level = 0
        if s.startswith("# "):
            flush()
            buf_level = 1
            buf = [s[2:].strip()]
            flush()
            continue
        if s.startswith("## "):
            flush()
            buf_level = 2
            buf = [s[3:].strip()]
            flush()
            continue
        if s.startswith("### "):
            flush()
            buf_level = 3
            buf = [s[4:].strip()]
            flush()
            continue
        if s.startswith("#"):
            continue
        buf_level = 0
        buf.append(s)
    flush()
    return blocks


def remove_body_from_chapter_one(doc: Document) -> None:
    marker = None
    for i, para in enumerate(doc.paragraphs):
        t = (para.text or "").strip()
        if t.startswith("CHAPTER-1") or t.startswith("CHAPTER–1"):
            marker = para._element
            break
    if marker is None:
        raise RuntimeError("Could not find CHAPTER-1 marker in template.")
    body = doc.element.body
    start = None
    for idx, child in enumerate(body):
        if child is marker:
            start = idx
            break
    if start is None:
        raise RuntimeError("Chapter marker element not in document body.")
    # Keep sectPr (last child); remove everything from chapter start through penultimate.
    to_remove = list(body[start:-1])
    for el in to_remove:
        body.remove(el)


def scrub_duplicate_title_page(doc: Document, n_paragraphs: int = 28) -> None:
    for _ in range(min(n_paragraphs, len(doc.paragraphs))):
        delete_paragraph(doc.paragraphs[0])


def fix_submitted_by_student_line(doc: Document) -> None:
    paras = doc.paragraphs
    for i, para in enumerate(paras):
        if (para.text or "").strip() != "Submitted by":
            continue
        for j in range(i + 1, min(i + 5, len(paras))):
            if not (paras[j].text or "").strip():
                paras[j].text = STUDENT_BLOCK
                return
        return


def cleanup_cvd_template_leftovers(doc: Document) -> None:
    """Remove split certificate/declaration tails and duplicate title-only lines."""
    for para in list(doc.paragraphs):
        t = para.text or ""
        if "LEARNING TECHNIQUES" in t:
            delete_paragraph(para)
            continue
        if "Mr. G. Vikram Chandra" in t:
            delete_paragraph(para)
            continue
        if "have carried out the major project work entitled" in t and "P. Satish Kumar" in t:
            delete_paragraph(para)
            continue
        stripped = t.strip()
        if stripped == PROJECT_TITLE.strip():
            idx = next(
                (i for i, p in enumerate(doc.paragraphs) if p._element is para._element),
                None,
            )
            prev_non_empty = ""
            if idx is not None:
                for j in range(idx - 1, -1, -1):
                    t2 = (doc.paragraphs[j].text or "").strip()
                    if t2:
                        prev_non_empty = t2
                        break
            if ("This is to certify" in prev_non_empty and PROJECT_TITLE in prev_non_empty) or (
                "Candidate" in prev_non_empty and "Declaration" in prev_non_empty
            ):
                delete_paragraph(para)
            continue
        if stripped.startswith("We have not submitted the matter"):
            delete_paragraph(para)


def apply_front_matter_replacements_safe(doc: Document) -> None:
    """Second pass-friendly replacements without fragile index logic."""
    for para in list(doc.paragraphs):
        t = para.text or ""
        # Declaration/certificate lines also mention the old CVD title; match those first.
        if t.startswith("This is to certify that P. Satish Kumar"):
            para.text = CERTIFICATE_TEXT
        elif t.startswith("We hereby declare that the work done"):
            para.text = DECLARATION_TEXT
        elif "CARDIOVASCULAR DISEASE" in t or "CVD PREDICTION" in t:
            para.text = PROJECT_TITLE
        elif t.startswith("We manifest our heartier thankfulness"):
            para.text = ACK_TEXT
        elif "Heart disease contributes to the highest death rates" in t:
            para.text = ABSTRACT_LEAD
        elif t.strip() in (
            "K. Meghana\t21091A3223",
            "S. Harshitha\t21091A3214",
            "C. Dharani\t21091A3211",
        ):
            delete_paragraph(para)
        elif "P. Satish Kumar\t21091A3243" in t:
            para.text = STUDENT_BLOCK
        elif "Mr. B. Bhaskara Rao M. Tech, (Ph.D.)\tMr. G. Vikram Chandra M. Tech" in t:
            para.text = f"{SUPERVISOR_PRIMARY}\t{SUPERVISOR_SECOND}"
        elif "Associate Professor & HOD, Dept. of CSE (DS)\tAssistant Professor, Dept. of CSE(DS)" in t:
            para.text = f"{SUPERVISOR_PRIMARY_ROLE}\t{SUPERVISOR_SECOND_ROLE}"
        elif t.strip() == "Mr. G. Vikram Chandra M. Tech":
            para.text = SUPERVISOR_SECOND
        elif "Assistant Professor, Dept. of CSE(DS)\tExternal Examiner" in t:
            para.text = f"{SUPERVISOR_SECOND_ROLE}\tExternal Examiner"
    fix_submitted_by_student_line(doc)
    cleanup_cvd_template_leftovers(doc)


def append_markdown_body(doc: Document, md_path: Path) -> None:
    blocks = parse_markdown_to_blocks(md_path)
    style_h1 = "Heading 1"
    style_h2 = "Heading 2"
    style_h3 = "Heading 3"
    for text, level in blocks:
        if text.startswith("Part ") and "Additional thesis" in text:
            doc.add_page_break()
        if level == 1 and text.upper().startswith("CHAPTER"):
            doc.add_page_break()
        para = doc.add_paragraph()
        if level == 1:
            para.style = style_h1
        elif level == 2:
            para.style = style_h2
        elif level == 3:
            para.style = style_h3
        run = para.add_run(text)
        run.font.name = "Times New Roman"
        run.font.size = Pt(12)
        para.paragraph_format.line_spacing = 1.5
        para.paragraph_format.space_after = Pt(6)
        para.alignment = WD_PARAGRAPH_ALIGNMENT.JUSTIFY


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", type=Path, default=None)
    ap.add_argument("--markdown", type=Path, default=DEFAULT_MD)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    tpl = args.template
    if tpl is None:
        tpl = DEFAULT_TEMPLATE if DEFAULT_TEMPLATE.exists() else FALLBACK_TEMPLATE
    if not tpl.exists():
        raise SystemExit(f"Template not found: {tpl}")

    if not args.markdown.exists():
        raise SystemExit(f"Markdown not found: {args.markdown}")

    doc = Document(str(tpl))
    scrub_duplicate_title_page(doc, 28)
    apply_front_matter_replacements_safe(doc)
    remove_body_from_chapter_one(doc)
    append_markdown_body(doc, args.markdown)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(args.output))
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()

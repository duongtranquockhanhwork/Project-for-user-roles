"""Build report/report.docx and report/report.pdf in the faculty report format.

The faculty template (report/mẫu/Midterm_Report.docx) is used as the base
document, so the cover pages, header logo, fonts, margins, page numbering,
acknowledgement / declaration pages and table of contents keep exactly the
template's format. Only the content is replaced.

Test tables are generated from tests/results/results.json (the last real
test run) and the screenshots from evidence/screenshots/.

Usage (Windows with Microsoft Word installed, after running the tests and
tests/capture_screenshots.py):
    python docs/build_report.py
"""
import copy
import html
import json
import pathlib
import re
import subprocess
import sys

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls
from docx.shared import Cm, Pt

SRC = pathlib.Path(__file__).resolve().parent.parent          # src_code/
PROJECT = SRC.parent                                           # submission root
TEMPLATE = PROJECT / "report" / "mẫu" / "Midterm_Report.docx"
OUT_DOCX = PROJECT / "report" / "report.docx"
OUT_PDF = PROJECT / "report" / "report.pdf"
SHOTS = SRC / "evidence" / "screenshots"
BUILD = SRC / "docs" / "build"

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
TEXT_WIDTH_DXA = 8788           # A4 minus template margins (3.5 cm + 2.0 cm)


# ---------------------------------------------------------------------------
# Low-level XML helpers (formatting copied from the template paragraphs)
# ---------------------------------------------------------------------------
def esc(text):
    return html.escape(str(text), quote=False)


def runs(text, size=None, bold=False, italic=False):
    """Inline markup: **bold**, `code`."""
    out = []
    for part in re.split(r"(\*\*.+?\*\*|`.+?`)", text):
        if not part:
            continue
        b, code, t = bold, False, part
        if part.startswith("**") and part.endswith("**"):
            b, t = True, part[2:-2]
        elif part.startswith("`") and part.endswith("`"):
            code, t = True, part[1:-1]
        rpr = ""
        if code:
            rpr += '<w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" w:cs="Consolas"/>'
        if b:
            rpr += "<w:b/><w:bCs/>"
        if italic:
            rpr += "<w:i/><w:iCs/>"
        sz = (size - 2 if code and size else (22 if code else size))
        if sz:
            rpr += f'<w:sz w:val="{sz}"/><w:szCs w:val="{sz}"/>'
        out.append(f'<w:r><w:rPr>{rpr}</w:rPr><w:t xml:space="preserve">{esc(t)}</w:t></w:r>')
    return "".join(out)


class Builder:
    def __init__(self, doc):
        self.doc = doc
        self.body = doc.element.body
        self.sect = self.body[-1]                  # final w:sectPr
        self.chapter = 0
        self.fig = 0
        self.tab = 0
        self.prefix = ""

    def _add(self, xml):
        el = parse_xml(xml)
        self.sect.addprevious(el)
        return el

    # -- headings --------------------------------------------------------
    def h1(self, text, center=False, page_break=None, chapter=True):
        if page_break is None:
            page_break = not chapter          # chapters flow; back matter starts a new page
        if chapter:
            self.chapter += 1
            self.prefix = str(self.chapter)
            self.fig = self.tab = 0
            text = f"CHAPTER {self.chapter}. {text}"
        jc = '<w:jc w:val="center"/>' if center else ""
        pb = "<w:pageBreakBefore/>" if page_break else ""
        self._add(f'<w:p {nsdecls("w")}><w:pPr><w:pStyle w:val="Heading1"/>{pb}'
                  f'<w:spacing w:after="300"/>{jc}<w:rPr><w:color w:val="auto"/></w:rPr></w:pPr>'
                  f'<w:r><w:rPr><w:b/><w:bCs/><w:color w:val="auto"/><w:sz w:val="30"/>'
                  f'<w:szCs w:val="30"/></w:rPr><w:t xml:space="preserve">{esc(text)}</w:t></w:r></w:p>')

    def appendix(self, letter, title):
        self.prefix = letter
        self.fig = self.tab = 0
        self.h1(f"APPENDIX {letter}. {title}", chapter=False)

    def h2(self, text):
        self._add(f'<w:p {nsdecls("w")}><w:pPr><w:pStyle w:val="Heading2"/><w:keepNext/>'
                  f'<w:spacing w:before="300" w:after="150"/><w:rPr><w:color w:val="auto"/></w:rPr>'
                  f'</w:pPr><w:r><w:rPr><w:b/><w:bCs/><w:color w:val="auto"/></w:rPr>'
                  f'<w:t xml:space="preserve">{esc(text)}</w:t></w:r></w:p>')

    # -- text ------------------------------------------------------------
    def p(self, text, indent=True, align="both", after=200, size=None, italic=False):
        ind = '<w:ind w:firstLine="720"/>' if indent else ""
        self._add(f'<w:p {nsdecls("w")}><w:pPr><w:spacing w:after="{after}" w:line="360" '
                  f'w:lineRule="auto"/>{ind}<w:jc w:val="{align}"/></w:pPr>'
                  f'{runs(text, size=size, italic=italic)}</w:p>')

    def bullets(self, items):
        for item in items:
            self._add(f'<w:p {nsdecls("w")}><w:pPr><w:pStyle w:val="ListParagraph"/>'
                      f'<w:numPr><w:ilvl w:val="0"/><w:numId w:val="3"/></w:numPr>'
                      f'<w:spacing w:after="100" w:line="300" w:lineRule="auto"/><w:jc w:val="both"/>'
                      f'</w:pPr>{runs(item)}</w:p>')

    def code(self, text):
        for line in text.splitlines():
            self._add(f'<w:p {nsdecls("w")}><w:pPr><w:spacing w:after="0" w:line="240" '
                      f'w:lineRule="auto"/><w:ind w:left="720"/></w:pPr>'
                      f'{runs("`" + line + "`" if line else " ")}</w:p>')

    # -- captions --------------------------------------------------------
    def _caption(self, style, label, text, before=0, after=300):
        self._add(f'<w:p {nsdecls("w")}><w:pPr><w:pStyle w:val="{style}"/>'
                  f'{"<w:keepNext/>" if style == "TableCaption" else ""}'
                  f'<w:spacing w:before="{before}" w:after="{after}" w:line="300" w:lineRule="auto"/>'
                  f'<w:jc w:val="center"/></w:pPr>'
                  f'<w:r><w:rPr><w:b/><w:bCs/><w:sz w:val="22"/><w:szCs w:val="22"/></w:rPr>'
                  f'<w:t xml:space="preserve">{esc(label)} </w:t></w:r>'
                  f'<w:r><w:rPr><w:sz w:val="22"/><w:szCs w:val="22"/></w:rPr>'
                  f'<w:t xml:space="preserve">{esc(text)}</w:t></w:r></w:p>')

    def figure(self, image, caption, width_cm=15.0):
        self.fig += 1
        para = self.doc.add_paragraph()
        pf = para.paragraph_format
        pf.alignment = 1
        pf.keep_with_next = True
        pf.space_before = Pt(6)
        pf.space_after = Pt(4)
        para.add_run().add_picture(str(image), width=Cm(width_cm))
        self._caption("FigureCaption", f"Figure {self.prefix}.{self.fig}.", caption)

    # -- tables ----------------------------------------------------------
    def table(self, caption, headers, rows, widths, size=20, first_col_center=False):
        self.tab += 1
        self._caption("TableCaption", f"Table {self.prefix}.{self.tab}.", caption, before=120, after=100)
        total = sum(widths)
        dxa = [round(w / total * TEXT_WIDTH_DXA) for w in widths]

        def cell(text, width, header=False, center=False):
            shd = ('<w:shd w:val="clear" w:color="auto" w:fill="ADADAD"/>' if header else "")
            jc = "center" if header or center else "left"
            paras = "".join(
                f'<w:p><w:pPr><w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/>'
                f'<w:jc w:val="{jc}"/></w:pPr>{runs(line, size=size, bold=header)}</w:p>'
                for line in str(text).split("\n"))
            return (f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/>{shd}'
                    f'<w:tcMar><w:top w:w="30" w:type="dxa"/><w:left w:w="90" w:type="dxa"/>'
                    f'<w:bottom w:w="30" w:type="dxa"/><w:right w:w="90" w:type="dxa"/></w:tcMar>'
                    f'<w:vAlign w:val="{"center" if header else "top"}"/></w:tcPr>{paras}</w:tc>')

        head = ('<w:tr><w:trPr><w:tblHeader/><w:cantSplit/></w:trPr>' +
                "".join(cell(h, dxa[i], header=True) for i, h in enumerate(headers)) + "</w:tr>")
        body = "".join(
            "<w:tr><w:trPr><w:cantSplit/></w:trPr>" +
            "".join(cell(v, dxa[i], center=(i == 0 and first_col_center)) for i, v in enumerate(r)) +
            "</w:tr>" for r in rows)
        border = '<w:{0} w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
        borders = "".join(border.format(b) for b in ("top", "left", "bottom", "right", "insideH", "insideV"))
        grid = "".join(f'<w:gridCol w:w="{w}"/>' for w in dxa)
        self._add(f'<w:tbl {nsdecls("w")}><w:tblPr><w:tblW w:w="{TEXT_WIDTH_DXA}" w:type="dxa"/>'
                  f'<w:jc w:val="center"/><w:tblBorders>{borders}</w:tblBorders>'
                  f'<w:tblLayout w:type="fixed"/><w:tblLook w:val="04A0"/></w:tblPr>'
                  f'<w:tblGrid>{grid}</w:tblGrid>{head}{body}</w:tbl>')
        self._add(f'<w:p {nsdecls("w")}><w:pPr><w:spacing w:after="120"/></w:pPr></w:p>')

    def page_break(self):
        self._add(f'<w:p {nsdecls("w")}><w:r><w:br w:type="page"/></w:r></w:p>')


def field_paragraph(instr):
    return parse_xml(
        f'<w:p {nsdecls("w")}><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        f'<w:r><w:instrText xml:space="preserve"> {instr} </w:instrText></w:r>'
        f'<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>(update field)</w:t></w:r>'
        f'<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')


def set_text(p_el, text):
    """Replace the visible text of a template paragraph, keeping the first run's format."""
    rs = [r for r in p_el.iter(W + "r") if r.find(W + "t") is not None]
    rs[0].find(W + "t").text = text
    rs[0].find(W + "t").set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    for r in rs[1:]:
        r.getparent().remove(r)


def add_caption_styles(doc):
    for name in ("FigureCaption", "TableCaption"):
        if name not in [s.style_id for s in doc.styles]:
            st = doc.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
            st.base_style = doc.styles["Normal"]
            st.font.size = Pt(11)
            st.font.italic = True
    # slightly tighter table of contents so it fits on one page
    for name in ("toc 1", "toc 2"):
        doc.styles[name].paragraph_format.space_after = Pt(3)
    # entries of the list of figures / tables (TOC level 9): plain text, dotted right tab
    try:
        toc9 = doc.styles["toc 9"]
    except KeyError:
        toc9 = doc.styles.add_style("toc 9", WD_STYLE_TYPE.PARAGRAPH)
    toc9.base_style = doc.styles["Normal"]
    toc9.font.bold = False
    toc9.font.italic = False
    toc9.font.size = Pt(13)
    pf = toc9.paragraph_format
    pf.left_indent = Cm(0)
    pf.space_after = Pt(4)
    pf.tab_stops.add_tab_stop(Cm(15.48), alignment=2, leader=1)


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------
def prepare_images():
    from playwright.sync_api import sync_playwright

    BUILD.mkdir(parents=True, exist_ok=True)
    svg = (SRC / "docs" / "dfd.svg").read_text(encoding="utf-8")
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="msedge", headless=True)
        except Exception:
            browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 900, "height": 430}, device_scale_factor=2.5)
        page.set_content(f"<html><body style='margin:0'>{svg}</body></html>")
        page.locator("svg").screenshot(path=str(BUILD / "dfd.png"))
        browser.close()

    def shot(name):
        return next(SHOTS.glob(f"*-{name}.png"))
    return {"dfd": BUILD / "dfd.png", "roster": shot("lecturer-assigned-roster")}


# ---------------------------------------------------------------------------
# Content
# ---------------------------------------------------------------------------
def front_matter(doc, group):
    b = list(doc.element.body.iterchildren())
    title = ["DESIGN, IMPLEMENT, AND AUDIT", "SECURE ACCESS CONTROL FOR A", "UNIVERSITY RECORDS SYSTEM"]
    for idx, line in zip((9, 10, 11), title):
        set_text(b[idx], line)
    for idx, line in zip((31, 32, 33), title):
        set_text(b[idx], line)
    set_text(b[12], "GROUP ASSIGNMENT REPORT")
    set_text(b[34], "GROUP ASSIGNMENT REPORT")
    for idx, m in zip((5, 6, 7), group["members"]):
        set_text(b[idx], f"{m['name'].upper()} – {m['student_id']}")
    for idx, m in zip((27, 28, 29), group["members"]):
        set_text(b[idx], f"{m['name'].upper()} – {m['student_id']}")
    set_text(b[37], group["instructor"])

    set_text(b[44], f"We would like to express our sincere gratitude to {group['instructor']}, our "
             "instructor, for his valuable guidance throughout this group assignment on designing, "
             "implementing and auditing secure access control for the Introduction to Information "
             "Security course. His lectures on access control, software security and database security "
             "helped us turn security principles into concrete, testable controls.")
    set_text(b[45], "We would also like to thank the Faculty of Information Technology, Ton Duc Thang "
             "University, for providing a supportive learning environment and equipping us with the "
             "foundational knowledge necessary to complete this assignment.")
    set_text(b[46], "Due to limitations in time and knowledge, this report may inevitably contain certain "
             "shortcomings. We sincerely welcome any comments and suggestions from our instructor to "
             "further improve and refine our work.")
    for idx in (48, 57):
        set_text(b[idx], f"Ho Chi Minh City, {group['date']}")
    set_text(b[55], f"We hereby declare that this report and the accompanying source code are our own work, "
             f"prepared under the guidance of {group['instructor']}. The system design, implementation, "
             "test results and evidence presented in this report were produced by our group, and all "
             "test results were obtained by actually running the test suite against the implemented "
             "system. All external sources used are cited in the references.")
    for tbl_idx in (51, 60):
        cells = [c for c in b[tbl_idx].iter(W + "tc")]
        for c, m in zip(cells[3:6], group["members"]):
            ps = [p for p in c.iter(W + "p")]
            if [r for r in ps[0].iter(W + "r") if r.find(W + "t") is not None]:
                set_text(ps[0], m["name"])

    # the TOC's last (field-end) paragraph is made 1 pt high so it cannot spill onto a blank page
    toc_end = list(b[63].iter(W + "p"))[-1]
    toc_end.insert(0, parse_xml(f'<w:pPr {nsdecls("w")}><w:spacing w:before="0" w:after="0" '
                                'w:line="20" w:lineRule="exact"/><w:rPr><w:sz w:val="2"/></w:rPr></w:pPr>'))

    # LIST OF FIGURES / LIST OF TABLES as real Word fields
    lof_heading, lof_entry = b[64], b[65]
    lof_entry.addprevious(field_paragraph('TOC \\h \\z \\t "FigureCaption,9"'))
    lot_heading = copy.deepcopy(lof_heading)
    set_text(lot_heading, "LIST OF TABLES")
    for bm in list(lot_heading.iter(W + "bookmarkStart")) + list(lot_heading.iter(W + "bookmarkEnd")):
        bm.getparent().remove(bm)
    lof_entry.addprevious(lot_heading)
    lof_entry.addprevious(field_paragraph('TOC \\h \\z \\t "TableCaption,9"'))
    lof_entry.getparent().remove(lof_entry)

    # Abbreviations: rebuild the template table with the template's own row format
    abbr_tbl = b[67]
    rows = abbr_tbl.findall(W + "tr")
    sample = rows[1]
    for r in rows[1:]:
        abbr_tbl.remove(r)
    for short, meaning in ABBREVIATIONS:
        row = copy.deepcopy(sample)
        cells = row.findall(W + "tc")
        set_text(cells[0].find(W + "p"), short)
        set_text(cells[1].find(W + "p"), meaning)
        abbr_tbl.append(row)

    set_text(b[69], ABSTRACT)
    set_text(b[70], "Keywords: role-based access control, default deny, IDOR, Argon2id, session management, "
             "CSRF, SQL injection, XSS, audit logging, least privilege, PostgreSQL.")

    # remove the template's chapters (everything after the front-matter section break)
    for el in b[72:-1]:
        el.getparent().remove(el)


ABBREVIATIONS = [
    ("RBAC", "Role-Based Access Control"),
    ("IDOR", "Insecure Direct Object Reference"),
    ("SQLi", "SQL Injection"),
    ("XSS", "Cross-Site Scripting"),
    ("CSRF", "Cross-Site Request Forgery"),
    ("CSP", "Content Security Policy"),
    ("DFD", "Data-Flow Diagram"),
    ("SoD", "Separation of Duties"),
    ("DBA", "Database Administrator"),
    ("MFA", "Multi-Factor Authentication"),
    ("TLS", "Transport Layer Security"),
    ("HSTS", "HTTP Strict Transport Security"),
    ("SHA-256", "Secure Hash Algorithm, 256-bit output"),
    ("OWASP", "Open Worldwide Application Security Project"),
    ("SR / TH / R", "Security requirement / Threat / Remaining risk identifiers used in this report"),
]

ABSTRACT = (
    "This report documents the design, implementation and audit of access control for a small web-based "
    "University Records System that stores user accounts, student profiles, courses, enrollments, grades "
    "and a security audit log. A threat model with twelve threats and sixteen security requirements was derived "
    "first, followed by an access-control matrix for five roles (Student, Lecturer, Registrar, Security "
    "Auditor and System Administrator) based on default deny, least privilege and separation of duties. The "
    "system was implemented with Flask and PostgreSQL 16 and enforces authorization at three layers: an "
    "endpoint permission check, a record-level ownership or course-assignment check, and database privileges "
    "and triggers. Passwords are hashed with Argon2id, sessions are server-side, every state-changing request "
    "requires an anti-CSRF token, and sensitive events are written to an append-only, hash-chained audit log. "
    "Students can register themselves (STUDENT role only) and join classes of at most 30 students with one "
    "lecturer, and course totals are computed by the database from four weighted grade components. Every user "
    "can change their password, and forgotten passwords are reset through an administrator-approved workflow "
    "in which no one, not even the administrator, ever sees a stored password. "
    "An automated suite of 58 security tests, including the 20 mandatory tests, passed completely. The report "
    "closes with seven remaining risks and the improvements recommended for each.")


def chapters(bld, results, img, group):
    rows = results["results"]
    by_id = {r["id"]: r for r in rows}

    # ------------------------------------------------------------------ 1
    bld.h1("INTRODUCTION")
    bld.h2("1.1 Background and Objectives")
    bld.p("Broken access control is ranked first in the OWASP Top 10: a single missing check lets one user read "
          "or change another user's data, and in university records that means personal data and grades. The "
          "objective is to secure such a system end to end: identify the threats, define an explicit "
          "access-control policy, implement it on the server and in the database, verify it with repeatable "
          "tests, and review the remaining risks.")
    bld.h2("1.2 Scope and Group Organization")
    lead = "; ".join(f"{m['label']} ({m['name']}): {m['responsibility'].lower()}" for m in group["members"])
    bld.p("The scope covers authentication, sessions, roles, server-side and record-level authorization, the "
          "academic features, database security, validation, output encoding and audit logging. Primary "
          "responsibilities were " + lead + ". All members reviewed the complete submission.")

    # ------------------------------------------------------------------ 2
    bld.h1("SYSTEM OVERVIEW")
    bld.p("The University Records System is a server-rendered web application written in Python 3.11 with Flask "
          "3.1 and served by gunicorn. Data is stored in PostgreSQL 16. The application and the database run as "
          "two Docker containers defined in `docker-compose.yml`; both ports are published on 127.0.0.1 only. "
          "The seed data contains 11 demo accounts (including a disabled account and the multi-role teaching "
          "assistant `ta01`, Student and Lecturer), five classes (IS101, DB201, NW301, SE202 and the still "
          "unassigned AI305), six student profiles, eleven enrollments and six grade records.")
    bld.p("Beyond the required operations, visitors can **register a student account**, students and lecturers "
          "use a **class catalog** to join a class or take an unassigned one, the registrar **creates classes** "
          "(one lecturer, at most 30 students) and arranges their lecturer and students, and lecturers enter "
          "**four grade components** (10/20/20/50 %). Every user can change their password, and a **forgot-password** "
          "request is answered by an administrator.")
    bld.p("The interface has a role-aware sidebar and a dashboard per role; permission lists are shown only to "
          "administrators and auditors. Hiding links is a convenience; every decision is taken on the server "
          "(screens in Appendix A).")

    # ------------------------------------------------------------------ 3
    bld.h1("THREAT MODEL AND SECURITY REQUIREMENTS")
    bld.h2("3.1 Assets, Users and Trust Boundaries")
    bld.p("**Assets:** A1 credentials, A2 session tokens, A3 personal data, A4 grades, A5 enrollments, A6 roles "
          "and policy, A7 audit log, A8 secrets. **Users:** the five roles (any may be malicious or compromised), "
          "anonymous visitors and the DBA. "
          "**Trust boundaries:** TB1 lies between the browser and the application (every request field, URL and "
          "cookie is untrusted). TB2 lies between the application and PostgreSQL (the application uses the "
          "restricted account `uni_app`). TB3 is the privileged maintenance channel (the Docker host and the "
          "database superuser), which lies outside the application (Figure 3.1).")
    bld.figure(img["dfd"], "System and data-flow diagram with trust boundaries TB1–TB3 and data stores D1–D4.",
               width_cm=12.5)
    bld.h2("3.2 Threat-Model Table")
    bld.p("Likelihood (L) and impact (I) are rated High, Medium or Low before controls. Residual risks are in "
          "Chapter 8; the sixteen derived security requirements are traced to tests in Appendix C.")
    bld.table("Threat model", ["ID", "Threat", "Asset", "Attack scenario", "L", "I", "Mitigation / control"], [
        ["TH1", "Account compromise", "A1, A2", "Password guessing or credential stuffing on /login; username "
         "enumeration via messages or timing.", "H", "H", "Argon2id; one generic error; dummy hash for unknown "
         "users; lockout after 5 failures (15 min); disabled accounts rejected; LOGIN_FAILURE logged."],
        ["TH2", "Session hijacking / fixation", "A2", "Stolen or planted session cookie; cookie replayed after "
         "logout.", "M", "H", "256-bit random token renewed at login, stored only as SHA-256; HttpOnly, "
         "SameSite=Strict; 30-min idle / 8-h absolute expiry; revoked at logout and on disable."],
        ["TH3", "Privilege escalation", "A6", "Forged requests to admin routes; administrator grants themself "
         "REGISTRAR; conflicting roles combined.", "M", "H", "Default-deny decorator on every route; no "
         "self role change; role-conflict table checked in app and by trigger; policy tables read-only."],
        ["TH4", "Insecure direct object reference", "A3–A5", "Student changes /students/1/grades to "
         "/students/2/grades.", "H", "H", "Record-level OWN / ASSIGNED / ALL check in every handler; same 403 "
         "for foreign and missing ids; RECORD_ACCESS_DENIED logged."],
        ["TH5", "SQL injection", "A1–A8", "' OR '1'='1' -- or UNION SELECT password_hash in login or search.",
         "M", "H", "Bound parameters for every query; LIKE wildcards escaped; allow-list validation; "
         "least-privilege DB account; generic errors."],
        ["TH6", "Cross-site scripting", "A2, A3", "Student stores <script> in the address field, which runs "
         "when staff view the profile.", "M", "H", "Jinja2 auto-escaping (no |safe); CSP script-src 'self' "
         "with no inline script; HttpOnly cookie."],
        ["TH7", "Unauthorized grade modification", "A4", "Student, registrar or unassigned lecturer posts "
         "/grades directly; teaching assistant grades their own enrollment.", "H", "H", "grade.write only for LECTURER with "
         "scope ASSIGNED; self-grading blocked; DB trigger grades_guard repeats the checks; all attempts logged."],
        ["TH8", "Audit-log tampering", "A7", "Insider deletes or edits log entries to hide an action.", "M",
         "H", "App account may only INSERT/SELECT; triggers block UPDATE/DELETE/TRUNCATE; SHA-256 hash chain "
         "with verification by the auditor."],
        ["TH9", "Leakage of credentials or records", "A1, A3, A8", "Secrets in Git, stack traces or SQL in error "
         "pages, tokens in logs.", "M", "H", ".env git-ignored; debug off and generic error pages; audit details "
         "sanitized; only hashes stored; ports bound to localhost."],
        ["TH10", "Cross-site request forgery", "A4, A6", "A malicious page makes a lecturer's browser submit a "
         "grade.", "M", "H", "Per-session synchronizer token on every POST; SameSite=Strict; CSRF_REJECTED "
         "logged."],
        ["TH11", "Abuse of self-service (registration, classes)", "A3–A6", "Sign-up with a forged role or by "
         "claiming another student's record; over-filling a class; a 2nd lecturer taking a class.", "M", "H",
         "Sign-up always STUDENT with a NEW profile; class capacity ≤ 30 and one lecturer enforced in app and DB "
         "(trigger, UNIQUE); self-service limited to oneself; all actions logged."],
        ["TH12", "Account takeover via password reset", "A1, A2", "Forged reset request; an administrator "
         "reading users' passwords.", "M", "H", "Uniform response; secret code; admin check and approval; one-time "
         "24 h temp password shown only to the requester; forced change."],
    ], [1.1, 2.4, 1.3, 4.4, 0.6, 0.6, 5.1], size=17, first_col_center=True)

    # ------------------------------------------------------------------ 4
    bld.h1("ACCESS-CONTROL POLICY")
    bld.h2("4.1 Access-Control Matrix")
    bld.p("In Table 4.1, Allow means the operation is permitted, Own means only the user's own record, Assigned "
          "means only courses assigned to the lecturer, Deny means the operation is explicitly prohibited, and "
          "N/A means the role has no such object. The same policy is stored in the database table "
          "`role_permissions`, and the auditor can view it at `/audit/policy`.")
    A, D = "Allow", "Deny"
    bld.table("Access-control matrix", ["Resource and operation", "Student", "Lecturer", "Registrar",
                                        "Auditor", "Administrator"], [
        ["View own profile, enrollments and grades", "Own", "N/A", "N/A", "N/A", "N/A"],
        ["Update own contact information", "Own", D, "via record update", D, D],
        ["View another student's profile", D, "Assigned course only", A, D, D],
        ["Search, create and update student records", D, D, A, D, D],
        ["View courses and course roster", D, "Assigned only", A, D, D],
        ["Create / drop enrollment", D, D, A, D, D],
        ["Create class (capacity ≤ 30)", D, D, A, D, D],
        ["Assign / replace / remove class lecturer (max. 1)", D, D, A, D, D],
        ["Join / leave a class (free seat; leave only if ungraded)", "Own", D, "via enrollment", D, D],
        ["Take an unassigned class as its lecturer", D, "Own, only if no lecturer", D, D, D],
        ["View another student's grade", D, "Assigned course only", A, D, D],
        ["Create / modify grade components", D, "Assigned course only, not own enrollment", D, D, D],
        ["Change own password (current password required)", "Own", "Own", "Own", "Own", "Own"],
        ["Change own display name", "Own", "Own", D, D, D],
        ["Answer forgotten-password requests (not own)", D, D, D, D, A],
        ["View any stored password", D, D, D, D, "Deny (not stored)"],
        ["Read audit log, verify integrity, read access policy", D, D, D, "Allow (read-only)", D],
        ["Create / disable / enable / unlock user", D, D, D, D, "Allow (not disable self)"],
        ["Assign / remove roles", D, D, D, D, "Allow (not own roles, no conflicting pair, keep one admin)"],
        ["Modify permissions and role definitions", D, D, D, D, "Deny (DBA migration only)"],
        ["Delete students, grades, users, audit entries", D, D, D, D, D],
    ], [4.8, 1.6, 2.6, 2.0, 1.8, 2.9], size=16)
    bld.p("Every role may log in, log out and open its dashboard. **Anonymous visitors** may only sign in or "
          "register; registration always creates a STUDENT account with a new student profile.", indent=False)
    bld.h2("4.2 Policy Explanation")
    bld.p("**Default deny.** An operation is allowed only if a row in `role_permissions` grants it. Every route "
          "must declare its rule (`@public`, `@login_required`, `@require_permission`); "
          "`verify_all_endpoints_declared()` stops the application at start-up otherwise. Requests without a "
          "session get 401; without the permission 403, logged, with no data changed.")
    bld.p("**Least privilege.** Each role holds only the permissions of its duties: the Registrar has "
          "`grade.read` but not `grade.write`, and the Administrator has no academic permission. Below the "
          "application, `uni_app` can neither delete academic data nor modify the policy (Chapter 6).")
    bld.p("**Separation of duties and role conflicts.** The table `role_conflicts` forbids three combinations: "
          "ADMIN+AUDITOR (whoever manages accounts must not audit those actions), LECTURER+REGISTRAR (enrolling "
          "and grading must be done by different people) and STUDENT+REGISTRAR (a registrar must not maintain "
          "their own record). Conflicts are checked when a role is assigned and again by the trigger "
          "`user_roles_conflict_guard`. An administrator cannot change their own roles, so separate academic "
          "access for an administrator requires a second administrator.")
    bld.p("**Multiple roles.** The effective permissions of a user are the union of the (permission, scope) "
          "pairs of all of the user's roles. The union never widens a scope. For example, `ta01` "
          "(Student+Lecturer) can read their own grades (OWN) and grade SE202 (ASSIGNED), but cannot open the "
          "DB201 roster or grade their own SE202 enrollment (tests T27 and T28).")
    bld.p("**Self-service and classes.** Registration ignores any role field and never links an existing record, "
          "so it cannot be used to read another student's grades. Self-service class actions act only on the "
          "user's own enrollment or teaching assignment; arranging other people remains a registrar duty "
          "(`course.manage`, `enrollment.manage`). A lecturer may take only a class without a lecturer and in which "
          "they are not enrolled. Renaming is denied to holders of ADMIN, AUDITOR or REGISTRAR (deny overrides); "
          "the administrator answers reset requests but never learns the new password.")
    bld.p("**Ownership and course-assignment checks.** Handlers load the object and call `can_access_student()` "
          "or `can_access_course()`: OWN requires `students.user_id` = session user, ASSIGNED a `course_lecturers` "
          "row. For a grade the course is taken from the stored enrollment, never from the client.")

    # ------------------------------------------------------------------ 5
    bld.h1("SECURITY ARCHITECTURE AND IMPLEMENTATION")
    bld.p("Every request passes the same pipeline (Figure 3.1): session check, route access rule, CSRF token, "
          "input validation and record scope, parameterized SQL in one transaction, then auto-escaped output with "
          "security headers (CSP, X-Frame-Options DENY, nosniff, no-referrer, no-store).")
    bld.h2("5.1 Authentication and Session Handling")
    bld.p("Passwords are hashed with Argon2id (64 MiB, 3 iterations, 4 lanes); a CHECK constraint rejects any "
          "other value. Wrong passwords, unknown, disabled and locked accounts all return \"Invalid username or "
          "password.\", and unknown usernames still cost one hash verification. Five failures lock an account "
          "for 15 minutes. Each login issues a new random 256-bit token. Only its SHA-256 hash "
          "is stored in the `sessions` table, together with the CSRF token and the expiry. Logout revokes the "
          "session on the server, and disabling an account revokes all of that account's sessions "
          "(`security.py`, `routes/auth.py`). Registration and password change apply the same policy "
          "(12–128 characters, confirmation, not containing the username); a change needs the current password "
          "(failures count towards lockout) and revokes other sessions. For a reset (`routes/account.py`) the "
          "requester gets a 96-bit code (stored as SHA-256); after approval a temporary password is generated on "
          "reveal, shown once, valid 24 h, and forces a password change.")
    bld.h2("5.2 Authorization")
    bld.p("`source/app/authz.py` loads the user's roles and the scoped permissions from the database on every "
          "request, so a role change takes effect immediately. The decorator checks the permission. The handlers "
          "in `routes/students.py` and `routes/courses.py` then check the scope of the specific record. Grade "
          "writes additionally reject self-grading and inactive enrollments. The administration handlers enforce "
          "the self-change, role-conflict and last-administrator rules.")
    bld.h2("5.3 Grading and Class Management")
    bld.p("A grade row holds four components; the course total `score` is a generated column "
          "(0.1·P1 + 0.2·P2 + 0.2·Mid + 0.5·Final), so it cannot be written by any client and stays empty until all "
          "components exist. The student page shows every component and a credit-weighted overall average. "
          "Class handlers check capacity and the single-lecturer rule before writing; the database repeats both.")
    bld.h2("5.4 Input Validation and Output Encoding")
    bld.p("`validators.py` applies allow-list rules (formats, lengths, no control characters, scores 0–10 with two "
          "decimals); bodies over 64 KB are rejected. Templates are auto-escaped and use only inline SVG, one "
          "stylesheet and one script (`static/app.js`, usability only), so the CSP `script-src 'self'; style-src "
          "'self'` holds. Toast messages come from a fixed server-side list (`?notice=grade_saved`), so no request "
          "text is reflected.")
    bld.h2("5.5 Security Audit Logging")
    bld.p("`audit.py` records the eight required event types plus registration, lockout, CSRF, class and record "
          "events, each with timestamp, actor, event type, target, result and JSON details (e.g. old and new "
          "grade components); secret keys are stripped. Successful changes are logged in the same transaction, "
          "rejections in a separate one, so they are recorded although nothing changes.")
    bld.h2("5.6 Error Handling and Secrets")
    bld.p("Debug mode is off; generic pages for 400–500 show no stack trace, SQL or configuration. A database guard "
          "violation (42501) becomes 403 (DB_GUARD_DENIED), a constraint violation (class full, second lecturer) "
          "400. Secrets live only in the git-ignored `.env`; the container runs as an unprivileged user.")

    # ------------------------------------------------------------------ 6
    bld.h1("DATABASE-SECURITY CONTROLS")
    bld.bullets([
        "**Separate accounts.** The DBA account `uni_dba` is used only for initialization. The application connects "
        "as `uni_app` (password from the environment, created by `database/init/00-create-roles.sh`): no "
        "superuser, CREATEROLE, CREATEDB or BYPASSRLS, owns no table; CONNECT is revoked from PUBLIC.",
        "**Table and column grants.** No DELETE on users, students, enrollments or grades; UPDATE only on "
        "named columns (the four grade components, never the total; no username or class-code change); policy "
        "tables SELECT-only; `audit_logs` INSERT and SELECT only; `password_reset_requests` has no password "
        "column, no DELETE and only its workflow columns can be updated.",
        "**Integrity triggers.** `grades_guard` rejects any grade written by someone who is not an active, assigned "
        "lecturer, and rejects self-grading, even if the application layer were bypassed. "
        "`user_roles_conflict_guard` enforces separation of duties. `enrollments_capacity_guard` locks the class "
        "row and rejects a student beyond its capacity (≤ 30); `UNIQUE (course_id)` allows one lecturer and "
        "`course_lecturers_guard` only active LECTURERs. CHECK constraints protect formats and score ranges.",
        "**Append-only, tamper-evident audit log.** A BEFORE INSERT trigger assigns the id, a server timestamp, "
        "`prev_hash` and `entry_hash` = SHA-256(prev_hash | fields) under an advisory lock. UPDATE, DELETE and "
        "TRUNCATE are blocked for every user, including the DBA. `audit_verify_chain()` reports the first "
        "altered entry.",
        "**Credential protection.** Only Argon2id and SHA-256 token hashes are stored; database logins use "
        "SCRAM-SHA-256; the port is bound to 127.0.0.1.",
    ])

    # ------------------------------------------------------------------ 7
    bld.h1("SECURITY TESTING")
    bld.h2("7.1 Test Plan")
    bld.p("The suite in `tests/` is automated and repeatable (pytest + requests against the running system, plus "
          "database checks). Each test declares ID, preconditions, role, action and expected result; the run records "
          "the actual result, PASS/FAIL and an evidence trace in `evidence/http/`. T01–T20 are mandatory; T21–T58 "
          "are original tests covering every additional control and feature.")
    bld.h2("7.2 Results")
    cats = {}
    for r in rows:
        c = cats.setdefault(r["category"], [0, 0, []])
        c[0] += 1
        c[1] += r["status"] == "PASS"
        c[2].append(r["id"])
    summary = [[k, v[0], v[1], v[0] - v[1], ", ".join(v[2])] for k, v in cats.items()]
    summary.append(["**Total**", f"**{results['total']}**", f"**{results['passed']}**",
                    f"**{results['total'] - results['passed']}**", "T01–T20 mandatory, T21–T58 original"])
    bld.p(f"The final run on {results['run_at']} passed **{results['passed']} of {results['total']}** tests "
          "(Table 7.1); all 20 mandatory tests T01–T20 passed. The complete table with preconditions, actions, "
          "actual results and evidence for every test is given in Appendix B.")
    bld.table("Test results by category", ["Category", "Tests", "Pass", "Fail", "Test IDs"], summary,
              [3.6, 1.2, 1.2, 1.2, 8.3], size=20)
    bld.p("Defects were found only in three tests (T24, T35, T42) and corrected.")

    # ------------------------------------------------------------------ 8
    bld.h1("REMAINING RISKS AND IMPROVEMENTS")
    bld.p("The final review checked the suggested areas against the actual code and configuration; Table 8.1 "
          "lists the remaining limitations; role explosion is low because permissions use scopes.")
    bld.table("Remaining limitations", ["#", "Limitation (verified)", "L", "I", "Risk",
                                        "Recommended improvement", "Implemented"], [
        ["R1", "No multi-factor authentication.", "M", "H", "High", "TOTP/WebAuthn for staff roles.", "No"],
        ["R2", "Reset depends on a manual identity check; admin-created and demo passwords are not force-changed.",
         "M", "M", "Medium", "Verified e-mail/SMS reset; force change of initial passwords.",
         "Partly (change + approved one-time reset)"],
        ["R3", "HTTP only on localhost; Secure cookie and HSTS inactive.", "L", "H", "Medium",
         "TLS proxy, COOKIE_SECURE=true, HSTS.", "Partly (config switch)"],
        ["R4", "No encryption at rest; no backups.", "L", "H", "Medium", "Encrypted volume and backups, restore tests.",
         "No"],
        ["R5", "A DB superuser can disable triggers and rebuild the hash chain.", "L", "H", "Medium",
         "Anchor chain heads in WORM storage / SIEM.", "Partly (append-only + chain)"],
        ["R6", "Lockout can be abused; no per-IP rate limit.", "M", "L", "Low", "Per-IP throttling, CAPTCHA.",
         "Partly (admin unlock)"],
        ["R7", "No break-glass access; no CSRF token on login.", "L", "M", "Low",
         "Two-admin emergency role; login CSRF token.", "No"],
        ["R8", "Sign-up has no e-mail check or CAPTCHA; lecturers take open classes without approval.", "M", "L",
         "Low", "E-mail verification, throttling, approval of teaching.", "Partly (STUDENT only, logged)"],
    ], [0.8, 5.4, 0.6, 0.6, 1.5, 4.2, 2.6], size=17, first_col_center=True)

    # ------------------------------------------------------------------ 9
    bld.h1("CONCLUSION")
    bld.p("The group derived twelve threats and a default-deny, least-privilege policy with separation of duties, "
          "and implemented it at three layers: endpoint decorator, record-level scope check, and database "
          f"privileges and triggers. All {results['total']} automated tests passed, including the 20 mandatory "
          "tests. The main open risks are MFA, an automated reset channel, TLS, encryption at rest and external "
          "protection of the audit log.")

    # ------------------------------------------------------- contributions
    bld.h1("INDIVIDUAL CONTRIBUTION SUMMARY", center=True, chapter=False)
    bld.p("Each member's full statement (tasks completed, repository commits, technical decisions, problems "
          "solved, approximate hours and the contributions of the other members) is submitted separately in "
          "`contribution/member-a.pdf`, `member-b.pdf` and `member-c.pdf`. All members reviewed the complete "
          "submission.")
    bld.table("Individual contribution summary", ["Member", "Primary responsibility", "Summary of contribution"],
              [[f"{m['label']}\n{m['name']}", m["responsibility"],
                m.get("summary") or "<to be completed by the member>"] for m in group["members"]],
              [3.6, 4.4, 7.5], size=20)

    # ------------------------------------------------------ appendix A: demo
    shots = json.loads((SHOTS / "index.json").read_text(encoding="utf-8"))
    by_section = {}
    for item in shots:
        by_section.setdefault(item["section"], []).append(item)

    from PIL import Image

    def gallery(section, width=14.5):
        for item in by_section.get(section, []):
            ref = f" ({item['test']})" if item["test"] else ""
            with Image.open(SHOTS / item["file"]) as im:
                px = im.width
            # component crops (e.g. the login card) are shown at their natural scale, not stretched
            w = width if px >= 1000 else round(width * px / 1440 * 1.45, 1)
            bld.figure(SHOTS / item["file"], item["caption"] + ref + ".", width_cm=w)

    bld.appendix("A", "SYSTEM DEMONSTRATION")
    bld.p("This appendix walks through the implemented system screen by screen, grouped by role. Every screenshot "
          "was captured automatically from the running application by `tests/capture_screenshots.py` (seed data, "
          "1440 × 900 viewport). The figure captions name the test case that the screen illustrates, so each "
          "image can be traced to Appendix B.")
    bld.h2("A.1 Interface Design")
    bld.p("The interface, branded UniRecords, uses one layout for all roles. A dark sidebar lists only the "
          "sections that the user's permissions allow, grouped as Overview, My studies, Academic, Administration "
          "and Security. A top bar shows a breadcrumb, the signed-in user with role badges and a logout button. "
          "Each page starts with a header and summary tiles, followed by cards holding tables or forms. Status is "
          "colour-coded consistently: grades by band (excellent, good, pass, fail), enrollments and accounts by "
          "badges, and audit results as Success, Denied or Failure.")
    bld.p("Interaction is enhanced by the external script `static/app.js`: smooth page transitions, entrance "
          "animations, count-up statistics, a loading state on buttons, confirmation dialogs before destructive "
          "actions (drop, disable) and auto-hiding confirmation toasts. The script carries no security logic. "
          "Animations are disabled for users who prefer reduced motion, and the layout adapts to mobile screens "
          "with a slide-in menu. Because the icons are inline SVG and all styles and scripts are served from the "
          "application itself, the strict Content Security Policy remains unchanged.")
    bld.h2("A.2 Authentication")
    bld.p("The sign-in page (Figure A.1) combines a product panel with the login form. The password field can be "
          "revealed with the eye button, and a link leads new students to registration. Whatever the reason "
          "for a failure (wrong password, unknown user, disabled or locked account, or an injection payload), the "
          "page shows the same message, as Figures A.2–A.4 show.")
    gallery("authentication")
    bld.h2("A.3 Self-Registration and Class Catalog")
    bld.p("A visitor creates a student account with name, username, e-mail and a confirmed password. Invalid input "
          "is rejected on the server with all messages at once. A successful sign-up returns to the login page with "
          "a confirmation; the new student receives a fresh student code and can immediately join an open class "
          "from the catalog, whose cards show lecturer, credits and seat usage.")
    gallery("registration")
    bld.h2("A.4 Student Portal")
    bld.p("A student's dashboard summarises their own studies (active courses, credits, published grades and the "
          "average) and offers quick actions. The profile page shows the official record next to a self-service "
          "form limited to email, phone and address. The grade page lists the four components of every course, "
          "the colour-coded total and the credit-weighted overall average. The catalog shows enrolled, open and "
          "full classes; a class cannot be left once grades exist.")
    gallery("student")
    bld.h2("A.5 Lecturer Workspace")
    bld.p("Lecturers see only their assigned classes. The roster has one input per grade component with its weight "
          "and the computed total. After saving, a toast confirms the change, which is audited with old and new "
          "values. For the multi-role account `ta01`, the own SE202 enrollment shows \"Own enrollment\" instead "
          "of inputs; the server and the database trigger reject such a request anyway (T27). In the catalog a "
          "lecturer can take a class that has no lecturer.")
    gallery("lecturer")
    bld.h2("A.6 Registrar Workspace")
    bld.p("The registrar works with all student records (searchable list, creation form) and all classes. A new "
          "class gets a code, title, credits, semester, a capacity of at most 30 and optionally its lecturer. The "
          "class page lets the registrar replace or remove the single lecturer, add students by code while seats "
          "remain, and remove students. The registrar can view grades but has no grade input anywhere.")
    gallery("registrar")
    bld.h2("A.7 Administrator Console")
    bld.p("The administrator's dashboard contains account statistics only, with no academic figures. The Users & "
          "roles page lists every account with role chips and its status (active, locked or disabled). It "
          "provides account actions and role assignment, and a Safeguards card states the separation-of-duties "
          "rules that the server enforces.")
    gallery("administrator")
    bld.h2("A.8 Account Self-Service and Password Reset")
    bld.p("Every role has a My account page. Students and lecturers can rename themselves; staff names are locked, "
          "and every role can change its password after confirming the current one. A forgotten password starts "
          "with a public request that returns a reference code once. The administrator's inbox shows the "
          "requester, whether the e-mail matches the profile and the message, with Approve and Reject plus a "
          "reply. With the code, the requester reads the reply and reveals a one-time temporary password; signing "
          "in with it leads straight to a forced password change.")
    gallery("account")
    bld.h2("A.9 Rejected Operations")
    bld.p("Unauthorized requests receive a uniform Access denied page (HTTP 403) that gives no detail about the "
          "protected resource. The figures below were produced by requests that bypass the user interface: a "
          "changed id in the URL (IDOR), or a hand-crafted POST with a valid CSRF token. They demonstrate that "
          "hiding a button is not the control; the server-side check is.")
    gallery("rejections", width=13)
    bld.h2("A.10 Input Handling and Session Termination")
    bld.p("A stored script payload is rendered as text because of auto-escaping, and the CSP would block it "
          "anyway. After logout, the previous session is revoked on the server, and any request with it receives "
          "the sign-in-required page (HTTP 401).")
    gallery("input")
    bld.h2("A.11 Security Auditor Console")
    bld.p("The auditor's dashboard monitors audit volume, denied actions and failed logins. The audit log can be "
          "filtered by event type, result and actor, and the details of each entry are shown as key–value chips. "
          "The integrity page recomputes the SHA-256 hash chain in the database. The policy page renders the "
          "permission matrix, role conflicts and role assignments directly from the database, read-only.")
    gallery("auditor")
    bld.h2("A.12 Database and Test Evidence")
    bld.p("The last two figures show the content of the users table, which holds only Argon2id hashes, and the "
          "automatically generated test report.")
    gallery("database", width=14)

    # -------------------------------------------------- appendix B: results
    bld.appendix("B", "COMPLETE SECURITY TEST RESULTS")
    bld.p(f"Generated from `tests/results/results.json` (run at {results['run_at']}, "
          f"{results['passed']}/{results['total']} passed). Reproduce with `python -m pytest tests`. Raw request "
          "and response traces are stored in `evidence/http/`.", indent=False)
    bld.table("Complete security test results", ["ID", "User / role", "Preconditions", "Request / action",
                                                 "Expected result", "Actual result", "Pass/ Fail", "Evidence"],
              [[r["id"], r["role"], r["pre"], r["action"], r["expected"], r["actual"], r["status"],
                r["evidence"].replace("evidence/http/", "http/")] for r in rows],
              [0.9, 1.7, 1.9, 2.5, 2.3, 3.6, 1.0, 1.6], size=15, first_col_center=True)

    # ------------------------------------------- appendix C: traceability
    bld.appendix("C", "REQUIREMENTS TRACEABILITY AND DEMO ACCOUNTS")
    bld.table("Security requirements, threats and verifying tests", ["ID", "Security requirement", "Threats",
                                                                     "Verified by"], [
        ["SR1", "Username/password login; passwords stored only as Argon2id hashes.", "TH1, TH9", "T01, T05"],
        ["SR2", "Generic login errors; no account enumeration; disabled accounts cannot log in.", "TH1",
         "T02, T03, T21"],
        ["SR3", "Repeated failed logins lock the account temporarily.", "TH1", "T22"],
        ["SR4", "Random server-side sessions, HttpOnly/SameSite cookies, renewed at login, invalid after logout "
         "or disabling.", "TH2", "T04, T23, T24, T25"],
        ["SR5", "Every endpoint denied unless explicitly permitted; checked on the server.", "TH3, TH7",
         "T08, T13, T15, T17, T33, T34"],
        ["SR6", "Records accessible only to the owner, the assigned lecturer or the registrar.", "TH4",
         "T06, T07, T09, T26, T31"],
        ["SR7", "Grade components written only by the assigned lecturer, never for their own enrollment; total "
         "computed by the DB; enforced in the DB too.", "TH7", "T10, T11, T27, T43, T47"],
        ["SR8", "Role changes only by administrators, not on themselves, no conflicting combinations.", "TH3",
         "T16, T28, T29, T30"],
        ["SR9", "Parameterized SQL, server-side validation, output encoding.", "TH5, TH6",
         "T18, T19, T35, T36, T38"],
        ["SR10", "State-changing requests require an anti-CSRF token.", "TH10", "T32"],
        ["SR11", "Sensitive actions and rejections in an append-only, tamper-evident log without secrets.",
         "TH8, TH9", "T20, T39, T40, T41, T42"],
        ["SR12", "No stack trace, SQL or configuration in errors; least-privilege DB account; no secrets in the "
         "repository.", "TH5, TH9", "T37, T44"],
        ["SR13", "Self-registration creates only STUDENT accounts with a new profile and validates input.", "TH11",
         "T45, T46"],
        ["SR14", "Classes are created only by the registrar; one lecturer and at most 30 students per class; "
         "self-service limited to oneself.", "TH11, TH3", "T48, T49, T50, T51, T52"],
        ["SR15", "Every user can change their password (current password, policy, other sessions revoked); only "
         "students and lecturers can rename.", "TH1, TH2", "T53, T54"],
        ["SR16", "Password reset: uniform request response, secret code, admin approval, one-time 24 h temporary "
         "password visible only to the requester, forced change; no stored or admin-visible passwords.",
         "TH12", "T55, T56, T57, T58"],
    ], [1.1, 8.6, 2.2, 3.6], size=20, first_col_center=True)
    bld.table("Demo accounts (password of every account: <username>@Demo2026)", ["Username", "Role(s)", "Notes"], [
        ["admin01, admin02", "ADMIN", "Two administrators (dual control for role changes)"],
        ["registrar01", "REGISTRAR", ""],
        ["auditor01", "AUDITOR", ""],
        ["lecturer01", "LECTURER", "Assigned IS101, DB201"],
        ["lecturer02", "LECTURER", "Assigned NW301 (AI305 has no lecturer yet)"],
        ["ta01", "STUDENT + LECTURER", "Student S2026004 (IS101, NW301, SE202); lecturer of SE202"],
        ["student01, student02, student03", "STUDENT", "S2026001, S2026002, S2026003"],
        ["disabled01", "STUDENT", "Disabled account (S2026005)"],
    ], [5.0, 4.0, 6.5], size=20)

    # ------------------------------------------------- references (last)
    bld.h1("REFERENCES", center=True, chapter=False)
    refs = [
        "OWASP Foundation, \"OWASP Top 10:2021,\" 2021. [Online]. Available: https://owasp.org/Top10/",
        "OWASP Foundation, \"Authorization Cheat Sheet,\" OWASP Cheat Sheet Series, 2024.",
        "OWASP Foundation, \"Password Storage Cheat Sheet\" and \"Session Management Cheat Sheet,\" OWASP Cheat "
        "Sheet Series, 2024.",
        "OWASP Foundation, \"Cross-Site Request Forgery Prevention Cheat Sheet,\" OWASP Cheat Sheet Series, 2024.",
        "A. Biryukov, D. Dinu, D. Khovratovich and S. Josefsson, \"Argon2 Memory-Hard Function for Password "
        "Hashing and Proof-of-Work Applications,\" RFC 9106, IETF, Sep. 2021.",
        "P. Grassi et al., \"Digital Identity Guidelines: Authentication and Lifecycle Management,\" NIST SP "
        "800-63B, 2017 (updated 2020).",
        "D. F. Ferraiolo, R. Sandhu, S. Gavrila, D. R. Kuhn and R. Chandramouli, \"Proposed NIST Standard for "
        "Role-Based Access Control,\" ACM Trans. Inf. Syst. Secur., vol. 4, no. 3, pp. 224–274, 2001.",
        "The PostgreSQL Global Development Group, \"PostgreSQL 16 Documentation: Privileges, Triggers and "
        "Client Authentication,\" 2023.",
        "W3C, \"Content Security Policy Level 3,\" W3C Working Draft, 2024.",
        "W3C, \"Media Queries Level 5: prefers-reduced-motion,\" W3C Working Draft, 2023.",
        "Pallets Projects, \"Flask 3.1 Documentation – Security Considerations,\" 2024.",
    ]
    for i, ref in enumerate(refs, 1):
        bld.p(f"[{i}] {ref}", indent=False, align="left", after=120)


# ---------------------------------------------------------------------------
# Word automation: update TOC / list of figures / list of tables, export PDF
# ---------------------------------------------------------------------------
PS_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$word = New-Object -ComObject Word.Application
$word.Visible = $false
try {
  $doc = $word.Documents.Open('{docx}')
  $doc.Fields.Update() | Out-Null
  foreach ($t in $doc.TablesOfContents) { $t.Update() }
  $doc.Repaginate()
  foreach ($t in $doc.TablesOfContents) { $t.Update() }
  $doc.Save()
  $doc.ExportAsFixedFormat('{pdf}', 17)
  $pages = $doc.ComputeStatistics(2)
  $out = @()
  foreach ($p in $doc.Paragraphs) {
    if ($p.OutlineLevel -eq 1) {
      $out += ('{0}|{1}|{2}' -f $p.Range.Information(3), $p.Range.Information(1), $p.Range.Text.Trim())
    }
  }
  $doc.Close()
  "PAGES=$pages"
  $out
} finally { $word.Quit() }
"""


def word_finalize():
    script = BUILD / "finalize.ps1"
    script.write_text(PS_SCRIPT.replace("{docx}", str(OUT_DOCX)).replace("{pdf}", str(OUT_PDF)),
                      encoding="utf-8-sig")
    res = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        raise SystemExit("Word automation failed:\n" + res.stderr)
    return res.stdout


def main():
    results = json.loads((SRC / "tests" / "results" / "results.json").read_text(encoding="utf-8"))
    group = json.loads((SRC / "docs" / "group.json").read_text(encoding="utf-8"))
    img = prepare_images()
    doc = Document(str(TEMPLATE))
    add_caption_styles(doc)
    front_matter(doc, group)
    chapters(Builder(doc), results, img, group)
    OUT_DOCX.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(OUT_DOCX))
    if sys.platform == "win32" and "--no-word" not in sys.argv:
        print(word_finalize())
    print("written:", OUT_DOCX.name, OUT_PDF.name)


if __name__ == "__main__":
    main()

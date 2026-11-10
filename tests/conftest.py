"""Shared fixtures for the security test suite.

The tests are black-box HTTP tests against the running application plus a few
read-only database inspections. Each test is tagged with
@pytest.mark.case(...) metadata; at the end of the run the results table
(ID, preconditions, role, action, expected, actual, pass/fail, evidence) is
written to evidence/test-results.md, evidence/test-results.html and
tests/results/results.json. Raw HTTP evidence for each test is saved in
evidence/http/<ID>.txt (session cookies are redacted).
"""
import datetime as dt
import html
import json
import os
import pathlib
import re

import psycopg2
import psycopg2.extras
import pytest
import requests
from dotenv import dotenv_values

ROOT = pathlib.Path(__file__).resolve().parent.parent
EVIDENCE_DIR = ROOT / "evidence"
HTTP_DIR = EVIDENCE_DIR / "http"
RESULTS_DIR = ROOT / "tests" / "results"

ENV = {**dotenv_values(ROOT / ".env"), **os.environ}
BASE_URL = ENV.get("TEST_BASE_URL", "http://localhost:8000")
DB_PARAMS = dict(host=ENV.get("TEST_DB_HOST", "127.0.0.1"),
                 port=int(ENV.get("TEST_DB_PORT", "5433")), dbname="uni_records")
SESSION_COOKIE = "urs_session"
GENERIC_LOGIN_ERROR = "Invalid username or password."

RESULTS = []


def demo_password(username):
    return f"{username}@Demo2026"


WEIGHTS = {"process1": "0.10", "process2": "0.20", "midterm": "0.20", "final_exam": "0.50"}


def weighted_total(components):
    """Expected course total: 10 % / 20 % / 20 % / 50 %, rounded to 2 decimals."""
    from decimal import ROUND_HALF_UP, Decimal
    total = sum(Decimal(str(components[k])) * Decimal(w) for k, w in WEIGHTS.items())
    return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------
class Client:
    def __init__(self):
        self.http = requests.Session()
        self._csrf = None

    def url(self, path):
        return BASE_URL + path

    def get(self, path, **kw):
        return self.http.get(self.url(path), allow_redirects=False, timeout=15, **kw)

    def post(self, path, data=None, csrf=True, **kw):
        data = dict(data or {})
        if csrf and "csrf_token" not in data:
            data["csrf_token"] = self.csrf()
        return self.http.post(self.url(path), data=data, allow_redirects=False, timeout=15, **kw)

    def csrf(self):
        if self._csrf is None:
            page = self.get("/account").text     # reachable by every signed-in user
            match = re.search(r'name="csrf-token" content="([^"]*)"', page)
            self._csrf = match.group(1) if match else ""
        return self._csrf

    def login(self, username, password=None):
        self._csrf = None
        return self.post("/login", {"username": username,
                                    "password": password if password is not None
                                    else demo_password(username)}, csrf=False)

    @property
    def session_token(self):
        return self.http.cookies.get(SESSION_COOKIE)


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def login_as():
    def _login(username, password=None):
        c = Client()
        r = c.login(username, password)
        assert r.status_code == 302, f"login of {username} failed with {r.status_code}"
        return c
    return _login


# ---------------------------------------------------------------------------
# Database inspection (read-only use of the application account, or the DBA
# account for the audit-log tamper test)
# ---------------------------------------------------------------------------
def _connect(user, password):
    conn = psycopg2.connect(user=user, password=password,
                            cursor_factory=psycopg2.extras.RealDictCursor, **DB_PARAMS)
    conn.autocommit = True
    return conn


@pytest.fixture(scope="session")
def app_db():
    conn = _connect("uni_app", ENV["APP_DB_PASSWORD"])
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def dba_db():
    conn = _connect(ENV.get("DBA_USER", "uni_dba"), ENV["DBA_PASSWORD"])
    yield conn
    conn.close()


def q(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall() if cur.description else None


def q1(conn, sql, params=()):
    rows = q(conn, sql, params)
    return rows[0] if rows else None


def ids(app_db):
    """Look up ids by natural keys so tests do not depend on serial values."""
    class Ids:
        def student(self, code):
            return q1(app_db, "SELECT id FROM students WHERE student_code = %s", (code,))["id"]

        def course(self, code):
            return q1(app_db, "SELECT id FROM courses WHERE code = %s", (code,))["id"]

        def user(self, username):
            return q1(app_db, "SELECT id FROM users WHERE username = %s", (username,))["id"]

        def enrollment(self, student_code, course_code):
            return q1(app_db, "SELECT e.id FROM enrollments e "
                              "JOIN students s ON s.id = e.student_id "
                              "JOIN courses c ON c.id = e.course_id "
                              "WHERE s.student_code = %s AND c.code = %s",
                      (student_code, course_code))["id"]

        def score(self, enrollment_id):
            """Snapshot of all grade components and the total (to prove 'unchanged')."""
            row = q1(app_db, "SELECT process1, process2, midterm, final_exam, score FROM grades "
                             "WHERE enrollment_id = %s", (enrollment_id,))
            return None if row is None else tuple(row.values())

        def total(self, enrollment_id):
            row = q1(app_db, "SELECT score FROM grades WHERE enrollment_id = %s", (enrollment_id,))
            return None if row is None else row["score"]
    return Ids()


@pytest.fixture
def lookup(app_db):
    return ids(app_db)


def last_audit(app_db, since_id, **filters):
    where = ["id > %s"]
    params = [since_id]
    for column, value in filters.items():
        where.append(f"{column} = %s")
        params.append(value)
    return q(app_db, "SELECT * FROM audit_logs WHERE " + " AND ".join(where) + " ORDER BY id",
             params)


@pytest.fixture
def audit_mark(app_db):
    """Highest audit id before the test, to find entries the test produced."""
    return q1(app_db, "SELECT coalesce(max(id), 0) AS m FROM audit_logs")["m"]


# ---------------------------------------------------------------------------
# Result recording
# ---------------------------------------------------------------------------
def _text_of(body):
    main = re.search(r"<main>(.*)</main>", body, re.S)
    text = main.group(1) if main else body
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", text, flags=re.S)
    text = re.sub(r'<input type="hidden" name="csrf_token"[^>]*>', "", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


class Record:
    def __init__(self, case_id):
        self.case_id = case_id
        self.actual_text = ""
        self.lines = []

    def actual(self, text):
        self.actual_text = text

    def http(self, label, response, raw_snippet=None):
        req = response.request
        body = req.body or ""
        if isinstance(body, bytes):
            body = body.decode("utf-8", "replace")
        body = re.sub(r"(password=)[^&]*", r"\1[REDACTED]", body)
        body = re.sub(r"(csrf_token=)[^&]*", r"\1[REDACTED]", body)
        self.lines.append(f"### {label}")
        self.lines.append(f"> {req.method} {req.path_url}")
        if body:
            self.lines.append(f"> body: {body}")
        self.lines.append(f"< HTTP {response.status_code}")
        for header in ("Location", "Content-Security-Policy", "Set-Cookie"):
            if header in response.headers:
                value = response.headers[header]
                if header == "Set-Cookie":
                    value = re.sub(r"(urs_session=)[^;]+", r"\1[REDACTED]", value)
                self.lines.append(f"< {header}: {value}")
        if raw_snippet:
            self.lines.append(f"< raw HTML excerpt: {raw_snippet}")
        text = _text_of(response.text)
        if text:
            self.lines.append(f"< page text: {text[:600]}")
        self.lines.append("")

    def note(self, label, value):
        self.lines.append(f"### {label}")
        self.lines.append(str(value))
        self.lines.append("")

    def save(self):
        if not self.lines:
            return ""
        HTTP_DIR.mkdir(parents=True, exist_ok=True)
        path = HTTP_DIR / f"{self.case_id}.txt"
        path.write_text(f"Evidence for {self.case_id} - generated {dt.datetime.now():%Y-%m-%d %H:%M:%S}\n"
                        f"Target: {BASE_URL}\n\n" + "\n".join(self.lines), encoding="utf-8")
        return f"evidence/http/{self.case_id}.txt"


@pytest.fixture
def record(request):
    marker = request.node.get_closest_marker("case")
    rec = Record(marker.kwargs["id"] if marker else request.node.name)
    request.node._record = rec
    return rec


def pytest_configure(config):
    config.addinivalue_line("markers", "case(id, category, role, pre, action, expected): test metadata")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when != "call" and not (report.when == "setup" and report.failed):
        return
    marker = item.get_closest_marker("case")
    if marker is None:
        return
    rec = getattr(item, "_record", None)
    actual = rec.actual_text if rec and rec.actual_text else ""
    if report.failed:
        message = str(call.excinfo.value).splitlines()[0] if call.excinfo else "failed"
        actual = (actual + " | " if actual else "") + f"FAILED: {message[:300]}"
    evidence = rec.save() if rec else ""
    RESULTS.append({**marker.kwargs, "actual": actual,
                    "status": "PASS" if report.passed else "FAIL",
                    "evidence": evidence, "test": item.nodeid})


def pytest_sessionfinish(session, exitstatus):
    if not RESULTS:
        return
    RESULTS.sort(key=lambda r: int(r["id"][1:]))
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    passed = sum(r["status"] == "PASS" for r in RESULTS)
    (RESULTS_DIR / "results.json").write_text(json.dumps(
        {"run_at": stamp, "base_url": BASE_URL, "passed": passed, "total": len(RESULTS),
         "results": RESULTS}, indent=2), encoding="utf-8")

    cols = ["id", "category", "role", "pre", "action", "expected", "actual", "status", "evidence"]
    heads = ["Test ID", "Category", "User / role", "Preconditions", "Request / action",
             "Expected result", "Actual result", "Pass/Fail", "Evidence"]
    md = [f"# Security test results", "",
          f"Run at {stamp} against {BASE_URL} - **{passed}/{len(RESULTS)} passed**", "",
          "| " + " | ".join(heads) + " |", "|" + "---|" * len(heads)]
    for r in RESULTS:
        md.append("| " + " | ".join(str(r.get(c, "")).replace("|", "\\|").replace("\n", " ")
                                     for c in cols) + " |")
    (EVIDENCE_DIR / "test-results.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    rows = "\n".join(
        "<tr class='{}'>{}</tr>".format(
            r["status"].lower(),
            "".join(f"<td>{html.escape(str(r.get(c, '')))}</td>" for c in cols))
        for r in RESULTS)
    by_cat = {}
    for r in RESULTS:
        stats = by_cat.setdefault(r["category"], [0, 0])
        stats[1] += 1
        stats[0] += r["status"] == "PASS"
    summary = " &middot; ".join(f"{html.escape(k)}: {v[0]}/{v[1]}" for k, v in by_cat.items())
    (EVIDENCE_DIR / "test-results.html").write_text(f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Security test results</title>
<style>
body{{font:13px/1.4 system-ui,Segoe UI,sans-serif;margin:24px;color:#1d2330}}
h1{{font-size:20px;margin:0 0 4px}} .sum{{margin:0 0 14px;color:#444}}
table{{border-collapse:collapse;width:100%}} th,td{{border:1px solid #ccd;padding:4px 6px;vertical-align:top;text-align:left}}
th{{background:#e9eef6}} tr.pass td:nth-child(8){{color:#127a3e;font-weight:700}}
tr.fail td{{background:#fde8e6}} tr.fail td:nth-child(8){{color:#b42318;font-weight:700}}
</style></head><body>
<h1>University Records System - security test results</h1>
<p class="sum">Run at {stamp} against {html.escape(BASE_URL)} &mdash; <b>{passed}/{len(RESULTS)} passed</b> ({summary})</p>
<table><thead><tr>{''.join(f'<th>{h}</th>' for h in heads)}</tr></thead><tbody>
{rows}
</tbody></table></body></html>""", encoding="utf-8")

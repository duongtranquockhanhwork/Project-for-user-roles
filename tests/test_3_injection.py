"""Injection and input-validation tests (T18-T19 mandatory, T35-T38 original)."""
import pytest

from conftest import GENERIC_LOGIN_ERROR, q1

case = pytest.mark.case

DB_ERROR_MARKERS = ("Traceback", "psycopg2", "SQL", "syntax error", "postgres",
                    "uni_app", "Werkzeug", "File \"/")

SQLI_LOGIN_PAYLOADS = [
    ("' OR '1'='1' --", "anything"),
    ("admin01'--", "x"),
    ("admin01", "' OR '1'='1"),
    ("x'; DROP TABLE users; --", "x"),
]


def assert_no_leak(text):
    for marker in DB_ERROR_MARKERS:
        assert marker not in text, f"response leaks '{marker}'"


@case(id="T18", category="Injection / validation", role="Anonymous",
      pre="Application running",
      action="POST /login with SQL-injection strings in username and password",
      expected="No unauthorized access or database error (401 generic message); users table intact")
def test_t18_sqli_login(client, record, app_db):
    for username, password in SQLI_LOGIN_PAYLOADS:
        r = client.login(username, password)
        record.http(f"username={username!r}", r)
        assert r.status_code == 401
        assert GENERIC_LOGIN_ERROR in r.text
        assert client.session_token is None
        assert_no_leak(r.text)
    assert q1(app_db, "SELECT count(*) AS n FROM users")["n"] >= 11
    record.actual(f"{len(SQLI_LOGIN_PAYLOADS)} payloads: all HTTP 401 with the generic message, "
                  "no session, no SQL error text; users table intact")


@case(id="T19", category="Injection / validation", role="Student (student01) + Registrar",
      pre="student01 logged in",
      action="Store <script>alert('xss')</script> in own address; view profile as student and registrar",
      expected="Value stored but rendered HTML-escaped; CSP forbids inline script; script does not execute")
def test_t19_stored_xss(login_as, record, lookup, app_db):
    payload = "<script>alert('xss')</script><img src=x onerror=alert(1)>"
    student = login_as("student01")
    sid = lookup.student("S2026001")
    original = q1(app_db, "SELECT email, phone, address FROM students WHERE id = %s", (sid,))
    try:
        r = student.post(f"/students/{sid}/contact",
                         {"email": original["email"] or "", "phone": original["phone"] or "",
                          "address": payload})
        assert r.status_code == 302
        stored = q1(app_db, "SELECT address FROM students WHERE id = %s", (sid,))["address"]
        assert stored == payload                                   # stored as data
        for who, c in (("student01", student), ("registrar01", login_as("registrar01"))):
            page = c.get(f"/students/{sid}")
            start = page.text.find('id="address">')
            snippet = page.text[start:start + 160]
            record.http(f"Profile viewed by {who}", page, raw_snippet=snippet)
            assert "<script>alert" not in page.text and "<img src=x" not in page.text
            assert "&lt;script&gt;alert(&#39;xss&#39;)&lt;/script&gt;" in page.text
            assert "script-src 'self'" in page.headers["Content-Security-Policy"]
    finally:
        student.post(f"/students/{sid}/contact", {"email": original["email"] or "",
                                                  "phone": original["phone"] or "",
                                                  "address": original["address"] or ""})
    record.actual("Payload stored verbatim in DB but output as &lt;script&gt;... for both viewers; "
                  "CSP script-src 'self' present; no executable script in the page")


@case(id="T35", category="Injection / validation", role="Registrar (registrar01)",
      pre="registrar01 logged in",
      action="GET /students?q=<SQL-injection payloads> (OR 1=1, UNION SELECT password_hash, quotes)",
      expected="Payload treated as literal text: no extra rows, no hashes, no database error")
def test_t35_sqli_search(login_as, record):
    c = login_as("registrar01")
    payloads = ["' OR 1=1 --", "' UNION SELECT password_hash FROM users--",
                "'; SELECT pg_sleep(5); --", "\\' OR \\'1\\'=\\'1"]
    for payload in payloads:
        r = c.get("/students", params={"q": payload})
        record.http(f"q={payload!r}", r)
        assert r.status_code == 200
        assert "No matching students." in r.text
        assert "$argon2id$" not in r.text
        assert_no_leak(r.text)
    normal = c.get("/students", params={"q": "Nguyen"})
    assert "S2026001" in normal.text
    record.actual("All payloads HTTP 200 with 'No matching students.', no hashes or SQL errors; "
                  "a normal search still works")


@case(id="T36", category="Injection / validation", role="Lecturer (lecturer01)",
      pre="lecturer01 assigned to IS101",
      action="POST /grades with a component = 11, -1, abc, 8.555, NaN, 1e1, 10.01, all components empty, "
             "and enrollment_id = 1 OR 1=1",
      expected="Each rejected with 400 by server-side validation; grade unchanged")
def test_t36_score_validation(login_as, record, lookup):
    c = login_as("lecturer01")
    enr = lookup.enrollment("S2026002", "IS101")
    before = lookup.score(enr)
    for field, value in (("process1", "11"), ("process2", "-1"), ("midterm", "abc"), ("final_exam", "8.555"),
                         ("process1", "NaN"), ("final_exam", "1e1"), ("midterm", "10.01")):
        r = c.post("/grades", {"enrollment_id": enr, "process1": "5", field: value})
        record.http(f"{field}={value!r}", r)
        assert r.status_code == 400
    r = c.post("/grades", {"enrollment_id": enr, "process1": "", "process2": "", "midterm": "",
                           "final_exam": ""})
    record.http("all components empty", r)
    assert r.status_code == 400
    r = c.post("/grades", {"enrollment_id": "1 OR 1=1", "final_exam": "5"})
    record.http("enrollment_id='1 OR 1=1'", r)
    assert r.status_code == 400
    assert lookup.score(enr) == before
    record.actual(f"All 9 invalid inputs HTTP 400; score unchanged ({before})")


@case(id="T37", category="Injection / validation", role="Registrar / Anonymous",
      pre="Application running",
      action="Trigger errors: unknown URL, non-integer id, wrong method, oversized body, overlong search",
      expected="Generic error pages; no stack trace, SQL or configuration disclosed")
def test_t37_safe_error_pages(client, login_as, record):
    c = login_as("registrar01")
    checks = [
        ("GET /does-not-exist", client.get("/does-not-exist"), 404),
        ("GET /students/abc", c.get("/students/abc"), 404),
        ("GET /students/99999999999999999999", c.get("/students/99999999999999999999"), 404),
        ("PUT /login", client.http.put(client.url("/login"), allow_redirects=False), 405),
        ("POST 100 KB body", c.post("/students", {"full_name": "A" * 100_000}), 413),
        ("GET /students?q=<60 chars>", c.get("/students", params={"q": "x" * 60}), 400),
    ]
    for label, r, expected in checks:
        record.http(label, r)
        assert r.status_code == expected, label
        assert_no_leak(r.text)
    record.actual("404/404/404/405/413/400 with generic messages; no stack trace, SQL or config")


@case(id="T38", category="Injection / validation", role="Student (student01)",
      pre="student01 logged in",
      action="POST own contact with invalid email, invalid phone, control characters, 250-char address",
      expected="Rejected with 400; record unchanged")
def test_t38_contact_validation(login_as, record, lookup, app_db):
    c = login_as("student01")
    sid = lookup.student("S2026001")
    before = q1(app_db, "SELECT email, phone, address FROM students WHERE id = %s", (sid,))
    bad = [{"email": "not-an-email"}, {"phone": "12;DROP"}, {"address": "abc\x00def"},
           {"address": "x" * 250}, {"email": "a@b.c<script>"}]
    for data in bad:
        r = c.post(f"/students/{sid}/contact", data)
        record.http(f"contact={data!r}"[:80], r)
        assert r.status_code == 400
    assert q1(app_db, "SELECT email, phone, address FROM students WHERE id = %s", (sid,)) == before
    record.actual("All 5 invalid inputs HTTP 400 with validation messages; record unchanged")

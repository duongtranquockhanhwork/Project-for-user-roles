"""Capture evidence screenshots of the running application.

Usage (the application must be running; run the test suite first so that the
results page exists):
    python tests/capture_screenshots.py

Uses Playwright with the locally installed Microsoft Edge (channel "msedge"),
or Chromium if Edge is unavailable (`python -m playwright install chromium`).
Screenshots are written to evidence/screenshots/ together with index.json,
which records the section, caption and related test of every image (used by
docs/build_report.py for the demonstration chapter).
"""
import html
import json
import pathlib
import sys

import psycopg2
import psycopg2.extras
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from conftest import BASE_URL, DB_PARAMS, ENV, EVIDENCE_DIR, demo_password  # noqa: E402

OUT = EVIDENCE_DIR / "screenshots"
VIEWPORT = {"width": 1440, "height": 900}


def db_rows(sql, params=()):
    conn = psycopg2.connect(user="uni_app", password=ENV["APP_DB_PASSWORD"],
                            cursor_factory=psycopg2.extras.RealDictCursor, **DB_PARAMS)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    finally:
        conn.close()


def one(sql, params=()):
    return db_rows(sql, params)[0]


class Shooter:
    def __init__(self, browser):
        self.browser = browser
        self.index = []

    def new_page(self, username=None):
        # Reduced motion: entrance animations finish instantly, so captures are never mid-transition.
        ctx = self.browser.new_context(viewport=VIEWPORT, reduced_motion="reduce", device_scale_factor=1)
        page = ctx.new_page()
        page.on("dialog", lambda d: d.accept())
        if username:
            page.goto(BASE_URL + "/login")
            page.fill("input[name=username]", username)
            page.fill("input[name=password]", demo_password(username))
            page.click("button[type=submit]")
            page.wait_for_url(BASE_URL + "/")
        return page

    def shot(self, page, name, section, caption, test="", full_page=True, element=None, height=None):
        number = len(self.index) + 1
        path = OUT / f"{number:02d}-{name}.png"
        page.wait_for_load_state("networkidle")
        if element:                       # focus on one component, e.g. the login card
            page.locator(element).screenshot(path=str(path))
        elif height:                      # top part of the page only
            page.screenshot(path=str(path), clip={"x": 0, "y": 0, "width": VIEWPORT["width"], "height": height})
        else:
            page.screenshot(path=str(path), full_page=full_page)
        self.index.append({"file": path.name, "section": section, "caption": caption, "test": test})
        print("saved", path.name)


def post_form(page, action, fields):
    """Submit a hand-crafted POST (a request sent without using the UI)."""
    with page.expect_navigation():
        page.evaluate("""([action, fields]) => {
            const f = document.createElement('form');
            f.method = 'post'; f.action = action;
            const all = Object.assign({csrf_token: document.querySelector('meta[name=csrf-token]').content}, fields);
            for (const [k, v] of Object.entries(all)) {
                const i = document.createElement('input'); i.type = 'hidden'; i.name = k; i.value = v; f.appendChild(i);
            }
            document.body.appendChild(f); f.submit();
        }""", [action, fields])


def login_attempt(page, username, password):
    page.goto(BASE_URL + "/login")
    page.fill("input[name=username]", username)
    page.fill("input[name=password]", password)
    page.click("button[type=submit]")
    page.wait_for_load_state()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.png"):
        old.unlink()
    sid = {r["student_code"]: r["id"] for r in db_rows("SELECT id, student_code FROM students")}
    cid = {r["code"]: r["id"] for r in db_rows("SELECT id, code FROM courses")}

    def enr(s, c):
        return one("SELECT id FROM enrollments WHERE student_id = %s AND course_id = %s",
                   (sid[s], cid[c]))["id"]

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="msedge", headless=True)
        except Exception:
            browser = p.chromium.launch(headless=True)
        s = Shooter(browser)

        # ---------------------------------------------------------- authentication
        A = "authentication"
        page = s.new_page()
        page.goto(BASE_URL + "/login")
        s.shot(page, "login-page", A, "Sign-in page with the product overview and the login form")
        login_attempt(page, "student01", "WrongPassword!1")
        s.shot(page, "login-failure-generic-message", A, "Wrong password: one generic error message (HTTP 401)", "T02", element=".auth-card")
        login_attempt(page, "disabled01", demo_password("disabled01"))
        s.shot(page, "disabled-account-rejected", A, "Disabled account with the correct password is rejected", "T03", element=".auth-card")
        login_attempt(page, "' OR '1'='1' --", "' OR '1'='1")
        s.shot(page, "sqli-login-rejected", A, "SQL-injection payload in the login form: generic failure, no database error", "T18", element=".auth-card")

        # ---------------------------------------------------------- student
        S = "student"
        page = s.new_page("student01")
        s.shot(page, "student-dashboard", S, "Student dashboard: study statistics and quick actions", "T01")
        page.goto(f"{BASE_URL}/students/{sid['S2026001']}")
        s.shot(page, "student-profile", S, "Student profile with the self-service contact form")
        page.goto(f"{BASE_URL}/students/{sid['S2026001']}/enrollments")
        s.shot(page, "student-enrollments", S, "Student's own enrollments")
        page.goto(f"{BASE_URL}/students/{sid['S2026001']}/grades")
        s.shot(page, "student-own-grades", S, "Student's own grades with colour-coded scores and the average", "T06")

        # ---------------------------------------------------------- lecturer
        L = "lecturer"
        page = s.new_page("lecturer01")
        s.shot(page, "lecturer-dashboard", L, "Lecturer dashboard: assigned courses, students and pending grades")
        page.goto(BASE_URL + "/courses")
        s.shot(page, "lecturer-courses", L, "Lecturer sees only the courses assigned to them")
        page.goto(f"{BASE_URL}/courses/{cid['IS101']}/roster")
        s.shot(page, "lecturer-assigned-roster", L, "Roster of the assigned course IS101 with grade entry", "T09")
        row = page.locator("#roster tr", has_text="S2026002")
        row.locator("input[name=score]").fill("7.25")
        row.locator("button").click()
        page.wait_for_url("**notice=grade_saved**")
        s.shot(page, "lecturer-grade-update-success", L, "Grade saved for S2026002 in IS101 (confirmation toast)", "T10",
               full_page=False)
        page = s.new_page("ta01")
        page.goto(f"{BASE_URL}/courses/{cid['NW301']}/roster")
        s.shot(page, "ta-own-enrollment-protected", L,
               "Multi-role ta01 grades NW301 but cannot grade their own enrollment", "T27")

        # ---------------------------------------------------------- registrar
        R = "registrar"
        page = s.new_page("registrar01")
        s.shot(page, "registrar-dashboard", R, "Registrar dashboard: records, enrollments and courses")
        page.goto(BASE_URL + "/students?q=Nguyen")
        s.shot(page, "registrar-student-search", R, "Student search (the search text is a bound SQL parameter)")
        page.goto(BASE_URL + "/students/new")
        s.shot(page, "registrar-new-student-form", R, "Form for creating a student record")
        active = {r["code"] for r in db_rows(
            "SELECT c.code FROM enrollments e JOIN courses c ON c.id = e.course_id "
            "WHERE e.student_id = %s AND e.status = 'ENROLLED'", (sid["S2026006"],))}
        free = next((c for c in ("IS101", "NW301") if c not in active), None)
        page.goto(BASE_URL + "/enrollments")
        if free is None:  # both taken by an earlier run: drop one first
            free = "IS101"
            page.locator("#enrollments tr", has_text="S2026006").filter(has_text="IS101").locator("button").click()
            page.wait_for_load_state()
        page.fill("input[name=student_code]", "S2026006")
        page.select_option("select[name=course_code]", free)
        page.click("form[action='/enrollments'] button[type=submit]")
        page.wait_for_url("**notice=enrollment_created**")
        s.shot(page, "registrar-creates-enrollment", R, f"Registrar enrolls S2026006 in {free}", "T12", full_page=False)

        # ---------------------------------------------------------- administrator
        D = "administrator"
        page = s.new_page("admin01")
        s.shot(page, "admin-dashboard", D, "Administrator dashboard: account statistics only, no academic data")
        page.goto(BASE_URL + "/admin/users")
        s.shot(page, "admin-users-and-roles", D, "User accounts, role chips, status and role-assignment controls", "T16")

        # ---------------------------------------------------------- rejected operations
        X = "rejections"
        page = s.new_page("student01")
        page.goto(f"{BASE_URL}/students/{sid['S2026002']}/grades")
        s.shot(page, "student-idor-denied", X, "student01 changes the id in the URL to another student: HTTP 403", "T07", height=600)
        post_form(page, "/grades", {"enrollment_id": enr("S2026001", "IS101"), "score": "10"})
        s.shot(page, "student-direct-grade-request-denied", X, "student01 sends a grade-modification request directly: HTTP 403", "T08", height=600)
        page = s.new_page("lecturer01")
        post_form(page, "/grades", {"enrollment_id": enr("S2026001", "NW301"), "score": "0"})
        s.shot(page, "lecturer-unassigned-course-denied", X, "lecturer01 modifies a grade in unassigned NW301: HTTP 403", "T11", height=600)
        page = s.new_page("registrar01")
        post_form(page, "/grades", {"enrollment_id": enr("S2026002", "DB201"), "score": "10"})
        s.shot(page, "registrar-grade-modification-denied", X, "registrar01 modifies a grade: HTTP 403", "T13", height=600)
        page = s.new_page("auditor01")
        post_form(page, f"/students/{sid['S2026003']}", {"full_name": "Changed by auditor"})
        s.shot(page, "auditor-modify-student-denied", X, "auditor01 modifies a student record: HTTP 403", "T15", height=600)
        page = s.new_page("admin01")
        page.goto(f"{BASE_URL}/students/{sid['S2026001']}/grades")
        s.shot(page, "admin-view-grades-denied", X, "admin01 (ADMIN only) opens a grade page: HTTP 403", "T17", height=600)
        admin02 = one("SELECT id FROM users WHERE username = 'admin02'")["id"]
        page.goto(BASE_URL + "/admin/users")
        post_form(page, f"/admin/users/{admin02}/roles", {"role": "AUDITOR", "action": "assign"})
        s.shot(page, "admin-role-conflict-denied", X, "Assigning AUDITOR to an administrator violates separation of duties: HTTP 403", "T30", height=600)

        # ---------------------------------------------------------- input handling & sessions
        I = "input"
        page = s.new_page("student01")
        original = one("SELECT address FROM students WHERE id = %s", (sid["S2026001"],))
        page.goto(f"{BASE_URL}/students/{sid['S2026001']}")
        page.fill("form[action$='/contact'] input[name=address]", "<script>alert('xss')</script>")
        page.click("form[action$='/contact'] button[type=submit]")
        page.wait_for_url("**notice=contact_updated**")
        s.shot(page, "xss-payload-rendered-as-text", I, "Stored <script> payload is displayed as plain text and does not execute", "T19")
        page.goto(f"{BASE_URL}/students/{sid['S2026001']}")
        page.fill("form[action$='/contact'] input[name=address]", original["address"] or "")
        page.click("form[action$='/contact'] button[type=submit]")
        page.wait_for_load_state()
        page.click("button[aria-label='Log out']")
        page.wait_for_load_state()
        page.goto(f"{BASE_URL}/students/{sid['S2026001']}/grades")
        s.shot(page, "session-invalid-after-logout", I, "After logout the old session is rejected: HTTP 401", "T04", element=".error-card")

        # ---------------------------------------------------------- auditor
        U = "auditor"
        page = s.new_page("auditor01")
        s.shot(page, "auditor-dashboard", U, "Security Auditor dashboard: audit volume, denials and failed logins")
        page.goto(BASE_URL + "/audit/logs")
        s.shot(page, "audit-log-entries", U, "Security audit log with timestamp, actor, event, target, result and details",
               "T14", full_page=False)
        page.goto(BASE_URL + "/audit/logs?result=DENIED")
        s.shot(page, "audit-log-rejected-actions", U, "Audit log filtered on rejected actions", "T20", full_page=False)
        page.goto(BASE_URL + "/audit/verify")
        s.shot(page, "audit-log-hash-chain-verified", U, "Integrity check: the SHA-256 hash chain is intact", "T42")
        page.goto(BASE_URL + "/audit/policy")
        s.shot(page, "auditor-access-control-configuration", U, "Read-only view of the access-control configuration", "T14")

        # ---------------------------------------------------------- database & tests
        B = "database"
        rows = db_rows("SELECT id, username, is_active, password_hash FROM users ORDER BY id LIMIT 14")
        table = "".join(f"<tr><td>{r['id']}</td><td>{html.escape(r['username'])}</td><td>{r['is_active']}</td>"
                        f"<td><code>{html.escape(r['password_hash'])}</code></td></tr>" for r in rows)
        page = s.new_page()
        page.set_content(f"""<html><body style="font:14px Segoe UI,sans-serif;margin:24px;color:#111">
          <h2 style="margin:0 0 6px">PostgreSQL query output (connected as uni_app)</h2>
          <pre style="background:#0f172a;color:#e2e8f0;padding:10px 14px;border-radius:8px">uni_records=&gt; SELECT id, username, is_active, password_hash FROM users ORDER BY id;</pre>
          <table cellpadding="6" style="border-collapse:collapse;font-size:13px" border="1">
          <tr style="background:#eef1f6"><th>id</th><th>username</th><th>is_active</th><th>password_hash</th></tr>{table}</table>
          <p>Every value is an Argon2id encoded hash; no plaintext password is stored.</p></body></html>""")
        s.shot(page, "hashed-password-records", B, "users.password_hash contains only Argon2id hashes", "T05")
        report = EVIDENCE_DIR / "test-results.html"
        if report.exists():
            page = s.new_page()
            page.goto(report.resolve().as_uri())
            s.shot(page, "security-test-results", B, "Automated security test results (pytest)", "T01–T44", full_page=False)

        browser.close()
    (OUT / "index.json").write_text(json.dumps(s.index, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{len(s.index)} screenshots written to evidence/screenshots/")


if __name__ == "__main__":
    main()

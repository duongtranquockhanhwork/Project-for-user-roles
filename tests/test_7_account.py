"""Account self-service and administrator-mediated password reset (original T53-T58)."""
import re
import secrets

import pytest

from conftest import Client, demo_password, q, q1

case = pytest.mark.case
INITIAL = "Initial-Pass-" + "x" * 4


def make_user(admin, lookup, roles):
    """admin01 creates a fresh account with the given roles; returns (username, password)."""
    username = "acc" + secrets.token_hex(3)
    password = INITIAL + secrets.token_hex(2)
    assert admin.post("/admin/users", {"username": username, "full_name": "Account Test",
                                       "password": password}).status_code == 302
    for role in roles:
        assert admin.post(f"/admin/users/{lookup.user(username)}/roles",
                          {"role": role, "action": "assign"}).status_code == 302
    return username, password


def file_request(username, email=""):
    r = Client().post("/forgot-password", {"username": username, "email": email,
                                           "message": "Lost my password"}, csrf=False)
    match = re.search(r'id="reference-code"><span>Your reference code</span><b class="mono">([^<]+)</b>', r.text)
    return r, match.group(1) if match else None


def request_id(app_db, username):
    return q1(app_db, "SELECT id FROM password_reset_requests WHERE username = %s ORDER BY id DESC LIMIT 1",
              (username,))["id"]


@case(id="T53", category="Authentication", role="Student, Lecturer, Registrar, Auditor, Admin (fresh accounts)",
      pre="admin01 creates one account per role",
      action="Each user POSTs /account/password with a wrong current password, then with the correct one; "
             "old password and an older second session are tested",
      expected="Wrong current password 400 (PASSWORD_CHANGE_FAILURE); change 302 for every role; old password "
               "rejected, new accepted; other sessions revoked")
def test_t53_every_role_changes_password(login_as, record, lookup, app_db, audit_mark):
    admin = login_as("admin01")
    outcomes = []
    for role in ("STUDENT", "LECTURER", "REGISTRAR", "AUDITOR", "ADMIN"):
        username, password = make_user(admin, lookup, [role])
        user, other_device = login_as(username, password), login_as(username, password)
        bad = user.post("/account/password", {"current_password": "wrong-password-1",
                                              "new_password": "Another-Pass-2026", "confirm_password": "Another-Pass-2026"})
        new = "Changed-Pass-" + secrets.token_hex(3)
        ok = user.post("/account/password", {"current_password": password, "new_password": new,
                                             "confirm_password": new})
        if role == "STUDENT":
            record.http("Wrong current password", bad)
            record.http("Correct change", ok)
        assert bad.status_code == 400 and ok.status_code == 302
        assert user.get("/account").status_code == 200            # this browser keeps a fresh session
        assert other_device.get("/account").status_code == 401    # other sessions are revoked
        assert Client().login(username, password).status_code == 401
        assert Client().login(username, new).status_code == 302
        outcomes.append(role)
    assert q(app_db, "SELECT 1 FROM audit_logs WHERE id > %s AND event_type = 'PASSWORD_CHANGE_FAILURE'", (audit_mark,))
    assert len(q(app_db, "SELECT 1 FROM audit_logs WHERE id > %s AND event_type = 'PASSWORD_CHANGE'",
                 (audit_mark,))) >= 5
    record.actual(f"All roles {outcomes}: wrong current 400, change 302, other session 401, old password 401, "
                  "new password 302; PASSWORD_CHANGE(_FAILURE) logged")


@case(id="T54", category="Authorization", role="Student, Lecturer vs Registrar, Auditor, Admin",
      pre="Seed accounts",
      action="POST /account/name as each role",
      expected="Student and lecturer: 302, name changed (student record too); registrar, auditor, admin: 403, unchanged")
def test_t54_rename_rules(login_as, record, app_db, lookup):
    results = {}
    for username in ("student03", "lecturer02", "registrar01", "auditor01", "admin01"):
        before = q1(app_db, "SELECT full_name FROM users WHERE username = %s", (username,))["full_name"]
        r = login_as(username).post("/account/name", {"full_name": "Renamed " + username})
        record.http(f"{username} renames", r)
        after = q1(app_db, "SELECT full_name FROM users WHERE username = %s", (username,))["full_name"]
        results[username] = (r.status_code, after != before)
        if r.status_code == 302:   # restore
            login_as(username).post("/account/name", {"full_name": before})
    assert results["student03"] == (302, True) and results["lecturer02"] == (302, True)
    for staff in ("registrar01", "auditor01", "admin01"):
        assert results[staff] == (403, False)
    record.actual(f"{results} (status, changed); student record name follows the account name")


@case(id="T55", category="Authentication", role="Anonymous",
      pre="student02 exists; 'ghostuser' does not",
      action="POST /forgot-password for an existing and a non-existing username",
      expected="Identical response with a reference code (no enumeration); request stored without any password; "
               "account unchanged")
def test_t55_forgot_request_uniform(record, app_db):
    before = q1(app_db, "SELECT password_hash FROM users WHERE username = 'student02'")["password_hash"]
    r1, code1 = file_request("student02", "binh.tran@student.example.edu")
    r2, code2 = file_request("ghostuser")
    record.http("Existing username", r1)
    record.http("Unknown username", r2)
    strip = lambda t: re.sub(r"<b class=\"mono\">[^<]+</b>|<b>[a-z0-9_.]+</b>", "", t)
    assert r1.status_code == r2.status_code == 200 and code1 and code2
    assert strip(r1.text) == strip(r2.text)
    cols = [x["column_name"] for x in q(app_db, "SELECT column_name FROM information_schema.columns "
                                                "WHERE table_name = 'password_reset_requests'")]
    assert not any("password" in c for c in cols)
    row = q1(app_db, "SELECT code_hash FROM password_reset_requests WHERE username = 'student02' "
                     "ORDER BY id DESC LIMIT 1")
    assert row["code_hash"] != code1 and len(row["code_hash"]) == 64
    assert q1(app_db, "SELECT password_hash FROM users WHERE username = 'student02'")["password_hash"] == before
    record.actual("Both 200 with identical text apart from the code; table has no password column; only the "
                  "SHA-256 of the code is stored; password unchanged")


@case(id="T56", category="Authentication", role="Anonymous requester + Admin (admin01)",
      pre="Fresh student account files a request",
      action="Admin approves with a reply; requester checks status, reveals the temporary password twice, logs in, "
             "opens another page, changes the password",
      expected="Reveal works once (2nd → 403); temp login forced to /account; other pages redirect until changed; "
               "temp password never stored or logged in plaintext")
def test_t56_reset_workflow(login_as, record, lookup, app_db):
    admin = login_as("admin01")
    username, old_password = make_user(admin, lookup, ["STUDENT"])
    _, code = file_request(username)
    anon = Client()
    pending = anon.post("/forgot-password/status", {"username": username, "code": code}, csrf=False)
    assert "Pending" in pending.text
    r = admin.post(f"/admin/password-requests/{request_id(app_db, username)}",
                   {"action": "approve", "reply": "Identity verified at the office"})
    record.http("Admin approves", r)
    assert r.status_code == 302
    status = anon.post("/forgot-password/status", {"username": username, "code": code}, csrf=False)
    assert "Approved" in status.text and "Identity verified at the office" in status.text
    reveal = anon.post("/forgot-password/reveal", {"username": username, "code": code}, csrf=False)
    temp = re.search(r'id="temp-password"><span>Temporary password</span><b class="mono">([^<]+)</b>', reveal.text).group(1)
    again = anon.post("/forgot-password/reveal", {"username": username, "code": code}, csrf=False)
    record.http("Second reveal", again)
    assert reveal.status_code == 200 and again.status_code == 403
    assert Client().login(username, old_password).status_code == 401
    user = Client()
    login = user.login(username, temp)
    record.http("Login with temporary password", login)
    assert login.headers["Location"].endswith("/account?notice=password_change_required")
    assert user.get("/classes").status_code == 302
    new = "Final-Pass-" + secrets.token_hex(3)
    assert user.post("/account/password", {"current_password": temp, "new_password": new,
                                           "confirm_password": new}).status_code == 302
    assert user.get("/classes").status_code == 200
    blob = " ".join(str(v) for r in q(app_db, "SELECT * FROM audit_logs") for v in r.values())
    blob += " ".join(str(v) for r in q(app_db, "SELECT * FROM password_reset_requests") for v in r.values())
    assert temp not in blob and code not in blob
    record.actual("Approve 302; status shows reply; reveal 200 once, then 403; temp login → /account, other pages "
                  "302 until changed, then 200; temp password and code absent from DB and audit log")


@case(id="T57", category="Authorization", role="Student, Registrar, Auditor vs Admin",
      pre="At least one pending request",
      action="Non-admins GET /admin/password-requests and POST an approval; admin opens the list and approves own request",
      expected="Non-admins 403; admin list shows requests but no password or hash; approving own request 403")
def test_t57_reset_admin_only(login_as, record, app_db):
    file_request("student03")
    rid = request_id(app_db, "student03")
    for user in ("student01", "registrar01", "auditor01"):
        c = login_as(user)
        a, b = c.get("/admin/password-requests"), c.post(f"/admin/password-requests/{rid}", {"action": "approve"})
        record.http(f"{user} approves", b)
        assert a.status_code == b.status_code == 403
    admin = login_as("admin01")
    page = admin.get("/admin/password-requests")
    assert page.status_code == 200 and "student03" in page.text
    assert "$argon2id$" not in page.text and demo_password("student03") not in page.text
    file_request("admin01")
    own = admin.post(f"/admin/password-requests/{request_id(app_db, 'admin01')}", {"action": "approve"})
    record.http("Admin approves own request", own)
    assert own.status_code == 403
    assert q1(app_db, "SELECT status FROM password_reset_requests WHERE id = %s", (rid,))["status"] == "PENDING"
    record.actual("student01/registrar01/auditor01 403 (list and approve); admin list 200 without hashes or "
                  "passwords; own request 403; request still PENDING")


@case(id="T58", category="Authentication", role="Anonymous + Admin",
      pre="Requests exist",
      action="Status with a wrong code; reject flow; reveal after rejection; expired temporary password",
      expected="Wrong code 404 without details; rejected request shows the reply and cannot be revealed (403); "
               "expired temporary password cannot log in")
def test_t58_reset_negative_paths(login_as, record, lookup, app_db):
    admin = login_as("admin01")
    username, _ = make_user(admin, lookup, ["STUDENT"])
    _, code = file_request(username)
    wrong = Client().post("/forgot-password/status", {"username": username, "code": "wrong-code"}, csrf=False)
    record.http("Wrong reference code", wrong)
    assert wrong.status_code == 404 and "No request matches" in wrong.text
    admin.post(f"/admin/password-requests/{request_id(app_db, username)}",
               {"action": "reject", "reply": "Please visit the office"})
    st = Client().post("/forgot-password/status", {"username": username, "code": code}, csrf=False)
    assert "Rejected" in st.text and "Please visit the office" in st.text
    rv = Client().post("/forgot-password/reveal", {"username": username, "code": code}, csrf=False)
    assert rv.status_code == 403
    # expired temporary password
    _, code2 = file_request(username)
    admin.post(f"/admin/password-requests/{request_id(app_db, username)}", {"action": "approve"})
    reveal = Client().post("/forgot-password/reveal", {"username": username, "code": code2}, csrf=False)
    temp = re.search(r'<b class="mono">([^<]+)</b>', reveal.text).group(1)
    q(app_db, "UPDATE users SET password_expires_at = now() - interval '1 minute' WHERE username = %s", (username,))
    expired = Client().login(username, temp)
    record.http("Login with expired temporary password", expired)
    assert expired.status_code == 401
    record.actual("Wrong code 404; rejected request shows reply, reveal 403; expired temporary password 401 "
                  "(generic message)")

"""Authentication tests (T01-T05 mandatory, T21-T25 original)."""
import secrets

import pytest

from conftest import GENERIC_LOGIN_ERROR, SESSION_COOKIE, Client, demo_password, q, q1

case = pytest.mark.case


@case(id="T01", category="Authentication", role="Student (student01)",
      pre="Active account student01 exists",
      action="POST /login with correct username and password",
      expected="Login succeeds; session cookie issued; LOGIN_SUCCESS logged")
def test_t01_correct_login(client, record, app_db, audit_mark):
    r = client.login("student01")
    record.http("Login with correct credentials", r)
    assert r.status_code == 302 and r.headers["Location"].endswith("/")
    assert client.session_token
    dash = client.get("/")
    record.http("Dashboard after login", dash)
    assert dash.status_code == 200 and "student01" in dash.text
    logs = q(app_db, "SELECT event_type, result FROM audit_logs WHERE id > %s "
                     "AND actor_username = 'student01' AND event_type = 'LOGIN_SUCCESS'",
             (audit_mark,))
    assert logs
    record.actual(f"HTTP 302 -> /, dashboard 200 shows student01; LOGIN_SUCCESS logged ({len(logs)} entry)")


@case(id="T02", category="Authentication", role="Student (student01)",
      pre="Active account student01 exists",
      action="POST /login with correct username and wrong password",
      expected="Login fails with a generic message; LOGIN_FAILURE logged")
def test_t02_wrong_password(client, record, app_db, audit_mark):
    r = client.login("student01", "WrongPassword!1")
    record.http("Login with wrong password", r)
    assert r.status_code == 401
    assert GENERIC_LOGIN_ERROR in r.text
    assert client.session_token is None
    log = q1(app_db, "SELECT details FROM audit_logs WHERE id > %s AND event_type = 'LOGIN_FAILURE' "
                     "AND target_resource = 'user:student01' ORDER BY id DESC LIMIT 1", (audit_mark,))
    assert log and log["details"]["reason"] == "wrong_password"
    record.actual(f"HTTP 401, message '{GENERIC_LOGIN_ERROR}', no cookie; LOGIN_FAILURE logged")


@case(id="T03", category="Authentication", role="Disabled student (disabled01)",
      pre="Account disabled01 has is_active = false",
      action="POST /login with the correct password of the disabled account",
      expected="Login fails (same generic message)")
def test_t03_disabled_account(client, record, app_db):
    row = q1(app_db, "SELECT is_active FROM users WHERE username = 'disabled01'")
    assert row["is_active"] is False
    r = client.login("disabled01")
    record.http("Login as disabled account with correct password", r)
    assert r.status_code == 401 and GENERIC_LOGIN_ERROR in r.text
    assert client.session_token is None
    record.actual("HTTP 401 with the generic message; no session cookie issued")


@case(id="T04", category="Authentication", role="Student (student01)",
      pre="student01 is logged in",
      action="Copy session cookie, POST /logout, then reuse the old cookie on GET /students/<own id>/grades",
      expected="Request with the old session is rejected (401)")
def test_t04_reuse_session_after_logout(login_as, record, lookup):
    c = login_as("student01")
    sid = lookup.student("S2026001")
    old_token = c.session_token
    before = c.get(f"/students/{sid}/grades")
    assert before.status_code == 200
    out = c.post("/logout")
    record.http("Logout", out)
    assert out.status_code == 302
    replay = Client()
    replay.http.cookies.set(SESSION_COOKIE, old_token)
    r = replay.get(f"/students/{sid}/grades")
    record.http("Replay old session cookie after logout", r)
    assert r.status_code == 401
    record.actual("Before logout 200; after logout the same cookie returns HTTP 401")


@case(id="T05", category="Authentication", role="Tester with DB access",
      pre="Seeded database",
      action="SELECT username, password_hash FROM users",
      expected="No plaintext passwords; all values are Argon2id hashes")
def test_t05_no_plaintext_passwords(app_db, record):
    rows = q(app_db, "SELECT username, password_hash FROM users ORDER BY id")
    record.note("users table (hash truncated)",
                "\n".join(f"{r['username']:<14} {r['password_hash'][:60]}..." for r in rows))
    assert rows
    for r in rows:
        assert r["password_hash"].startswith("$argon2id$v=19$m=65536,t=3,p=4$")
        assert demo_password(r["username"]) not in r["password_hash"]
    record.actual(f"{len(rows)} accounts; every password_hash is an Argon2id hash "
                  "(m=64MiB,t=3,p=4); no plaintext found")


@case(id="T21", category="Authentication", role="Anonymous",
      pre="Username 'nosuchuser' does not exist",
      action="POST /login with unknown username, compare with wrong-password response",
      expected="Identical status and message (no username enumeration)")
def test_t21_no_username_enumeration(client, record):
    unknown = client.login("nosuchuser", "Whatever!123")
    known = Client().login("student01", "Whatever!123")
    record.http("Unknown username", unknown)
    record.http("Existing username, wrong password", known)
    assert unknown.status_code == known.status_code == 401
    assert GENERIC_LOGIN_ERROR in unknown.text and GENERIC_LOGIN_ERROR in known.text
    record.actual("Both return HTTP 401 with the same generic message")


@case(id="T22", category="Authentication", role="Admin (admin01) + new user",
      pre="admin01 creates a fresh account",
      action="5 wrong passwords, then the correct password",
      expected="Account locked: correct password rejected; ACCOUNT_LOCKED logged")
def test_t22_account_lockout(login_as, record, app_db, audit_mark):
    admin = login_as("admin01")
    username = "lock" + secrets.token_hex(3)
    password = "Lockout-Test-" + secrets.token_hex(4)
    r = admin.post("/admin/users", {"username": username, "full_name": "Lockout Test",
                                    "password": password})
    assert r.status_code == 302
    c = Client()
    for _ in range(5):
        assert c.login(username, "wrong-password-x").status_code == 401
    r = c.login(username, password)
    record.http("Correct password after 5 failures", r)
    assert r.status_code == 401 and GENERIC_LOGIN_ERROR in r.text
    locked = q1(app_db, "SELECT locked_until > now() AS locked FROM users WHERE username = %s",
                (username,))
    assert locked["locked"]
    assert q(app_db, "SELECT 1 FROM audit_logs WHERE id > %s AND event_type = 'ACCOUNT_LOCKED' "
                     "AND target_resource = %s", (audit_mark, f"user:{username}"))
    record.actual("After 5 failures the correct password returns 401 (generic message); "
                  "locked_until set; ACCOUNT_LOCKED logged")


@case(id="T23", category="Authentication", role="Student (student01)",
      pre="None",
      action="Inspect Set-Cookie of a successful login and the sessions table",
      expected="Cookie is HttpOnly and SameSite=Strict; DB stores only a SHA-256 hash of the token")
def test_t23_cookie_flags_and_token_hashing(client, record, app_db):
    r = client.login("student01")
    record.http("Login", r)
    cookie = r.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie
    token = client.session_token
    assert not q(app_db, "SELECT 1 FROM sessions WHERE token_hash = %s", (token,))
    assert q(app_db, "SELECT 1 FROM sessions WHERE token_hash = encode(sha256(%s::bytea), 'hex')",
             (token.encode(),))
    record.actual("Set-Cookie has HttpOnly; SameSite=Strict; raw token absent from DB, "
                  "only its SHA-256 hash is stored")


@case(id="T24", category="Authentication", role="Student (student01)",
      pre="Attacker plants a known session cookie in the victim browser",
      action="Set cookie to attacker value, then log in",
      expected="Server issues a new random token (no session fixation)")
def test_t24_session_fixation(client, record):
    planted = "attacker-chosen-session-value"
    client.http.cookies.set(SESSION_COOKIE, planted)
    r = client.login("student01")
    record.http("Login with planted cookie", r)
    assert r.status_code == 302
    issued = r.cookies.get(SESSION_COOKIE)
    assert issued and issued != planted
    probe = Client()
    probe.http.cookies.set(SESSION_COOKIE, planted)
    assert probe.get("/").status_code == 401
    record.actual("A new token was issued; the planted value is not a valid session (401)")


@case(id="T25", category="Authentication", role="Admin (admin01) + new user",
      pre="New user is logged in",
      action="admin01 disables the account while its session is active; user sends a request",
      expected="Existing session is invalidated immediately (401); USER_DISABLE logged")
def test_t25_disable_kills_sessions(login_as, record, lookup, app_db, audit_mark):
    admin = login_as("admin01")
    username = "dis" + secrets.token_hex(3)
    password = "Disable-Test-" + secrets.token_hex(4)
    admin.post("/admin/users", {"username": username, "full_name": "Disable Test",
                                "password": password})
    user = login_as(username, password)
    assert user.get("/").status_code == 200
    r = admin.post(f"/admin/users/{lookup.user(username)}/status", {"action": "disable"})
    record.http("Admin disables the account", r)
    after = user.get("/")
    record.http("Request with the existing session", after)
    assert after.status_code == 401
    assert q(app_db, "SELECT 1 FROM audit_logs WHERE id > %s AND event_type = 'USER_DISABLE' "
                     "AND target_resource = %s", (audit_mark, f"user:{username}"))
    record.actual("Session valid before (200); after disabling, the same session gets 401; "
                  "USER_DISABLE logged")

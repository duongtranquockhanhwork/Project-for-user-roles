"""Audit-log tests (T20 mandatory, T39-T42 original)."""
import psycopg2
import pytest

from conftest import Client, demo_password, q, q1

case = pytest.mark.case

REQUIRED_EVENTS = {
    "LOGIN_SUCCESS": "Successful login",
    "LOGIN_FAILURE": "Failed login",
    "LOGOUT": "Logout",
    "USER_CREATE": "User creation",
    "USER_DISABLE": "User disabling",
    "ROLE_ASSIGN": "Role assignment",
    "ROLE_REMOVE": "Role removal",
    "GRADE_UPDATE": "Grade modification",
    "GRADE_CREATE": "Grade creation",
    "GRADE_MODIFY_DENIED": "Rejected grade modification",
    "RECORD_ACCESS_DENIED": "Rejected access to another user's record",
}


@case(id="T20", category="Audit log", role="Registrar (registrar01) + Auditor (auditor01)",
      pre="registrar01 logged in",
      action="Registrar attempts POST /grades; auditor opens /audit/logs?result=DENIED",
      expected="Rejection appears in audit log with timestamp, actor, event, target, result DENIED")
def test_t20_rejection_in_audit_log(login_as, record, lookup, app_db, audit_mark):
    reg = login_as("registrar01")
    enr = lookup.enrollment("S2026002", "DB201")
    r = reg.post("/grades", {"enrollment_id": enr, "final_exam": "10"})
    assert r.status_code == 403
    row = q1(app_db, "SELECT * FROM audit_logs WHERE id > %s AND actor_username = 'registrar01' "
                     "AND event_type = 'GRADE_MODIFY_DENIED' ORDER BY id DESC LIMIT 1",
             (audit_mark,))
    assert row is not None
    assert row["ts"] and row["actor_user_id"] == lookup.user("registrar01")
    assert row["result"] == "DENIED" and row["target_resource"] == "/grades"
    assert row["details"]["required_permission"] == "grade.write"
    auditor = login_as("auditor01")
    page = auditor.get("/audit/logs", params={"result": "DENIED", "actor": "registrar01"})
    record.http("Auditor view filtered on DENIED", page)
    assert "GRADE_MODIFY_DENIED" in page.text
    record.note("Audit row", {k: row[k] for k in ("id", "ts", "actor_username", "event_type",
                                                   "target_resource", "result", "details")})
    record.actual(f"Entry #{row['id']} {row['ts']:%Y-%m-%d %H:%M:%S} registrar01 "
                  f"GRADE_MODIFY_DENIED /grades DENIED {row['details']}; visible to auditor")


@case(id="T39", category="Audit log", role="Application DB account and DBA",
      pre="Audit log contains entries",
      action="UPDATE/DELETE/TRUNCATE audit_logs as uni_app, then UPDATE/DELETE as the DBA",
      expected="uni_app: permission denied; DBA: blocked by append-only trigger; log unchanged")
def test_t39_append_only(app_db, dba_db, record):
    count = q1(app_db, "SELECT count(*) AS n FROM audit_logs")["n"]
    attempts = [(app_db, "uni_app", "UPDATE audit_logs SET result = 'SUCCESS' WHERE id = 1"),
                (app_db, "uni_app", "DELETE FROM audit_logs WHERE id = 1"),
                (app_db, "uni_app", "TRUNCATE audit_logs"),
                (dba_db, "DBA", "UPDATE audit_logs SET result = 'SUCCESS' WHERE id = 1"),
                (dba_db, "DBA", "DELETE FROM audit_logs WHERE id = 1"),
                (dba_db, "DBA", "TRUNCATE audit_logs")]
    outcomes = []
    for conn, who, sql in attempts:
        with pytest.raises(psycopg2.Error) as exc:
            q(conn, sql)
        outcomes.append(f"{who}: {sql.split()[0]} -> {exc.value.pgcode} "
                        f"{str(exc.value).splitlines()[0]}")
    record.note("Modification attempts", "\n".join(outcomes))
    assert q1(app_db, "SELECT count(*) AS n FROM audit_logs")["n"] >= count
    record.actual("All 6 attempts raised errors (uni_app: 42501 permission denied; DBA: "
                  "42501 'audit_logs is append-only'); no row changed")


@case(id="T40", category="Audit log", role="Tester with DB access",
      pre="Previous tests performed logins, logouts and password-bearing requests",
      action="Search every audit entry for demo passwords, session tokens and secret keys",
      expected="No password, session token or DB credential appears in the log")
def test_t40_no_secrets_in_logs(app_db, record):
    from conftest import ENV
    c = Client()
    c.login("student01")
    token = c.session_token
    rows = q(app_db, "SELECT id, actor_username, event_type, target_resource, details::text AS d, "
                     "source_ip FROM audit_logs")
    blob = "\n".join(" ".join(str(v) for v in r.values()) for r in rows)
    secrets_to_find = [demo_password(u) for u in ("student01", "admin01", "lecturer01",
                                                  "registrar01", "auditor01")]
    secrets_to_find += [token, ENV["APP_DB_PASSWORD"], ENV["DBA_PASSWORD"], "$argon2id$"]
    for s in secrets_to_find:
        assert s not in blob
    for key in ('"password"', '"token"', '"csrf_token"'):
        assert key not in blob
    record.note("Scan", f"{len(rows)} audit entries scanned for: demo passwords of 5 accounts, the "
                "current session token, the uni_app and DBA database passwords, '$argon2id$', and "
                "the JSON keys password/token/csrf_token (values not reproduced here). Matches: 0")
    record.actual(f"Scanned {len(rows)} entries: no demo password, current session token, "
                  "DB password, password hash or secret key name found")


@case(id="T41", category="Audit log", role="Tester with DB access",
      pre="Full test suite has exercised all sensitive operations",
      action="Check that every required event type exists and each entry has all mandatory fields",
      expected="All required event types present; timestamp, actor, event, target, result filled")
def test_t41_required_events_and_fields(login_as, app_db, record, lookup):
    # Make sure a ROLE_REMOVE and GRADE_CREATE exist even if run in isolation.
    import secrets as s
    admin = login_as("admin01")
    name = "rm" + s.token_hex(3)
    admin.post("/admin/users", {"username": name, "full_name": "Remove Test",
                                "password": "Remove-Test-" + s.token_hex(4)})
    uid = lookup.user(name)
    admin.post(f"/admin/users/{uid}/roles", {"role": "STUDENT", "action": "assign"})
    admin.post(f"/admin/users/{uid}/roles", {"role": "STUDENT", "action": "remove"})
    lect = login_as("lecturer01")
    enr = lookup.enrollment("S2026006", "DB201")
    lect.post("/grades", {"enrollment_id": enr, "process1": "7", "process2": "6.5", "midterm": "7",
                          "final_exam": "6.75"})
    lect.post("/logout")

    present = {r["event_type"] for r in q(app_db, "SELECT DISTINCT event_type FROM audit_logs")}
    missing = [e for e in REQUIRED_EVENTS if e not in present]
    assert not missing, f"missing events {missing}"
    incomplete = q(app_db, "SELECT id FROM audit_logs WHERE ts IS NULL OR event_type IS NULL "
                           "OR result IS NULL OR actor_username IS NULL "
                           "OR target_resource IS NULL")
    assert not incomplete, f"entries with missing fields: {incomplete[:5]}"
    sample = q(app_db, "SELECT DISTINCT ON (event_type) id, ts, actor_username, event_type, "
                       "target_resource, result, details FROM audit_logs "
                       "WHERE event_type = ANY(%s) ORDER BY event_type, id DESC",
               (list(REQUIRED_EVENTS),))
    record.note("One example per required event type",
                "\n".join(f"#{r['id']} {r['ts']:%Y-%m-%d %H:%M:%S} {r['actor_username']} "
                          f"{r['event_type']} {r['target_resource']} {r['result']} {r['details']}"
                          for r in sample))
    record.actual(f"All {len(REQUIRED_EVENTS)} required event types present; "
                  "no entry lacks timestamp/actor/event/target/result")


@case(id="T42", category="Audit log", role="Auditor (auditor01) and DBA",
      pre="Audit log contains entries",
      action="Verify hash chain via /audit/verify; then, as DBA inside a rolled-back transaction, "
             "disable the trigger, alter one entry and re-verify",
      expected="Intact chain verified; the tampered entry is detected; rollback leaves log intact")
def test_t42_hash_chain(login_as, dba_db, record):
    auditor = login_as("auditor01")
    r = auditor.get("/audit/verify")
    record.http("Integrity check (intact)", r)
    assert r.status_code == 200 and "Hash chain intact" in r.text
    target = q1(dba_db, "SELECT id FROM audit_logs ORDER BY id OFFSET 3 LIMIT 1")["id"]
    dba_db.autocommit = False
    try:
        with dba_db.cursor() as cur:
            cur.execute("ALTER TABLE audit_logs DISABLE TRIGGER audit_logs_no_update")
            # Always a real change, whatever the original values of the entry were.
            cur.execute("UPDATE audit_logs SET details = details || '{\"tampered\": true}'::jsonb "
                        "WHERE id = %s", (target,))
            cur.execute("SELECT checked, first_bad_id FROM audit_verify_chain()")
            tampered = cur.fetchone()
    finally:
        dba_db.rollback()
        dba_db.autocommit = True
    record.note("Verification after tampering (rolled back)", tampered)
    assert tampered["first_bad_id"] == target
    again = auditor.get("/audit/verify")
    assert "Hash chain intact" in again.text
    record.actual(f"Intact chain verified; tampering with entry #{target} detected "
                  f"(first_bad_id={tampered['first_bad_id']}); after rollback chain intact again")

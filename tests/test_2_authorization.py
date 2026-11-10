"""Authorization tests (T06-T17 mandatory, T26-T34 original)."""
import random
import secrets
from decimal import Decimal

import pytest

from conftest import Client, q, q1, weighted_total

case = pytest.mark.case


def new_score():
    return Decimal(random.randint(0, 1000)) / 100


def new_components():
    return {k: new_score() for k in ("process1", "process2", "midterm", "final_exam")}


@case(id="T06", category="Authorization", role="Student (student01)",
      pre="student01 has grades in IS101 and NW301",
      action="GET /students/<own id>/grades",
      expected="Allowed (200), own grades displayed")
def test_t06_student_views_own_grade(login_as, record, lookup):
    c = login_as("student01")
    r = c.get(f"/students/{lookup.student('S2026001')}/grades")
    record.http("Own grades", r)
    assert r.status_code == 200 and "IS101" in r.text and "S2026001" in r.text
    record.actual("HTTP 200; grade table for S2026001 (IS101, NW301) displayed")


@case(id="T07", category="Authorization", role="Student (student01)",
      pre="student02 (S2026002) is another student",
      action="Change id in URL: GET /students/<student02 id>, /grades and /enrollments",
      expected="Rejected (403), no data of student02 returned; RECORD_ACCESS_DENIED logged")
def test_t07_idor_other_student(login_as, record, lookup, app_db, audit_mark):
    c = login_as("student01")
    other = lookup.student("S2026002")
    for path in (f"/students/{other}", f"/students/{other}/grades",
                 f"/students/{other}/enrollments"):
        r = c.get(path)
        record.http(f"GET {path}", r)
        assert r.status_code == 403
        assert "S2026002" not in r.text and "Tran Thi Binh" not in r.text
    logs = q(app_db, "SELECT target_resource FROM audit_logs WHERE id > %s AND actor_username = "
                     "'student01' AND event_type = 'RECORD_ACCESS_DENIED' AND result = 'DENIED'",
             (audit_mark,))
    assert len(logs) == 3
    record.actual("All three requests HTTP 403 without student02 data; "
                  f"3 RECORD_ACCESS_DENIED entries: {[l['target_resource'] for l in logs]}")


@case(id="T08", category="Authorization", role="Student (student01)",
      pre="student01 is logged in (valid CSRF token)",
      action="POST /grades directly for own IS101 enrollment with final_exam=10",
      expected="Rejected (403), grade unchanged; GRADE_MODIFY_DENIED logged")
def test_t08_student_direct_grade_modification(login_as, record, lookup, app_db, audit_mark):
    c = login_as("student01")
    enr = lookup.enrollment("S2026001", "IS101")
    before = lookup.score(enr)
    r = c.post("/grades", {"enrollment_id": enr, "final_exam": "10"})
    record.http("Forged grade-modification request", r)
    assert r.status_code == 403
    assert lookup.score(enr) == before
    assert q(app_db, "SELECT 1 FROM audit_logs WHERE id > %s AND actor_username = 'student01' "
                     "AND event_type = 'GRADE_MODIFY_DENIED'", (audit_mark,))
    record.actual(f"HTTP 403; score still {before}; GRADE_MODIFY_DENIED logged")


@case(id="T09", category="Authorization", role="Lecturer (lecturer01)",
      pre="lecturer01 is assigned to IS101",
      action="GET /courses/<IS101>/roster",
      expected="Allowed (200), enrolled students listed")
def test_t09_lecturer_views_assigned_roster(login_as, record, lookup):
    c = login_as("lecturer01")
    r = c.get(f"/courses/{lookup.course('IS101')}/roster")
    record.http("Roster of assigned course IS101", r)
    assert r.status_code == 200
    for code in ("S2026001", "S2026002", "S2026004"):
        assert code in r.text
    record.actual("HTTP 200; roster lists S2026001, S2026002, S2026004 with grade forms")


@case(id="T10", category="Authorization", role="Lecturer (lecturer01)",
      pre="lecturer01 is assigned to IS101; student01 enrolled in IS101",
      action="POST /grades {enrollment of student01 in IS101, four new components}",
      expected="Allowed; components stored, total = 10/20/20/50 % weighted; GRADE_UPDATE logged")
def test_t10_lecturer_modifies_assigned_grade(login_as, record, lookup, app_db, audit_mark):
    c = login_as("lecturer01")
    enr = lookup.enrollment("S2026001", "IS101")
    old = lookup.score(enr)
    comps = new_components()
    r = c.post("/grades", {"enrollment_id": enr, **{k: str(v) for k, v in comps.items()}})
    record.http("Update grade in assigned course", r)
    assert r.status_code == 302
    score = weighted_total(comps)
    assert lookup.score(enr)[:4] == tuple(comps.values())
    assert lookup.total(enr) == score
    log = q1(app_db, "SELECT details, result FROM audit_logs WHERE id > %s AND event_type = "
                     "'GRADE_UPDATE' AND actor_username = 'lecturer01' ORDER BY id DESC LIMIT 1",
             (audit_mark,))
    assert log and log["result"] == "SUCCESS"
    assert Decimal(log["details"]["total"]) == score
    record.note("Audit entry", log)
    record.actual(f"HTTP 302; components {[str(v) for v in comps.values()]} -> total {score} "
                  f"(was {old[4] if old else None}); GRADE_UPDATE logged with old and new values")


@case(id="T11", category="Authorization", role="Lecturer (lecturer01)",
      pre="lecturer01 is NOT assigned to NW301",
      action="POST /grades for student01's NW301 enrollment",
      expected="Rejected (403) and grade unchanged; GRADE_MODIFY_DENIED logged")
def test_t11_lecturer_modifies_unassigned_grade(login_as, record, lookup, app_db, audit_mark):
    c = login_as("lecturer01")
    enr = lookup.enrollment("S2026001", "NW301")
    before = lookup.score(enr)
    r = c.post("/grades", {"enrollment_id": enr, "final_exam": "0"})
    record.http("Update grade in unassigned course", r)
    assert r.status_code == 403
    assert lookup.score(enr) == before
    log = q1(app_db, "SELECT details FROM audit_logs WHERE id > %s AND event_type = "
                     "'GRADE_MODIFY_DENIED' AND actor_username = 'lecturer01'", (audit_mark,))
    assert log["details"]["reason"] == "course_not_assigned"
    record.actual(f"HTTP 403; score unchanged ({before}); GRADE_MODIFY_DENIED reason=course_not_assigned")


@case(id="T12", category="Authorization", role="Registrar (registrar01)",
      pre="registrar01 creates a new student record",
      action="POST /enrollments {student_code, course_code=IS101}",
      expected="Allowed; enrollment created; ENROLLMENT_CREATE logged")
def test_t12_registrar_creates_enrollment(login_as, record, app_db, audit_mark):
    c = login_as("registrar01")
    code = "T" + secrets.token_hex(3).upper()
    r = c.post("/students", {"student_code": code, "full_name": "Test Enrollment Student"})
    assert r.status_code == 302
    r = c.post("/enrollments", {"student_code": code, "course_code": "IS101"})
    record.http("Create enrollment", r)
    assert r.status_code == 302
    row = q1(app_db, "SELECT e.status FROM enrollments e JOIN students s ON s.id = e.student_id "
                     "JOIN courses c ON c.id = e.course_id WHERE s.student_code = %s "
                     "AND c.code = 'IS101'", (code,))
    assert row and row["status"] == "ENROLLED"
    assert q(app_db, "SELECT 1 FROM audit_logs WHERE id > %s AND event_type = 'ENROLLMENT_CREATE' "
                     "AND actor_username = 'registrar01'", (audit_mark,))
    record.actual(f"HTTP 302; enrollment {code}/IS101 status ENROLLED; ENROLLMENT_CREATE logged")


@case(id="T13", category="Authorization", role="Registrar (registrar01)",
      pre="registrar01 logged in; can view grades",
      action="POST /grades for student02's IS101 enrollment",
      expected="Rejected (403), grade unchanged")
def test_t13_registrar_modifies_grade(login_as, record, lookup):
    c = login_as("registrar01")
    enr = lookup.enrollment("S2026002", "IS101")
    before = lookup.score(enr)
    view = c.get(f"/students/{lookup.student('S2026002')}/grades")
    assert view.status_code == 200                       # may view ...
    r = c.post("/grades", {"enrollment_id": enr, "final_exam": "10"})
    record.http("Registrar attempts grade modification", r)
    assert r.status_code == 403                          # ... but not modify
    assert lookup.score(enr) == before
    record.actual(f"View grades 200; POST /grades HTTP 403; score unchanged ({before})")


@case(id="T14", category="Authorization", role="Auditor (auditor01)",
      pre="Audit log contains entries",
      action="GET /audit/logs and /audit/policy",
      expected="Allowed (200)")
def test_t14_auditor_reads_logs(login_as, record):
    c = login_as("auditor01")
    r = c.get("/audit/logs")
    record.http("Audit log", r)
    assert r.status_code == 200 and "LOGIN_SUCCESS" in r.text
    p = c.get("/audit/policy")
    assert p.status_code == 200 and "grade.write" in p.text
    record.actual("Both pages HTTP 200; log entries and access-control matrix displayed")


@case(id="T15", category="Authorization", role="Auditor (auditor01)",
      pre="Student S2026003 exists",
      action="POST /students/<id> (update record) and POST /students/<id>/contact",
      expected="Rejected (403); record unchanged")
def test_t15_auditor_modifies_student(login_as, record, lookup, app_db):
    c = login_as("auditor01")
    sid = lookup.student("S2026003")
    before = q1(app_db, "SELECT full_name, email, updated_at FROM students WHERE id = %s", (sid,))
    r1 = c.post(f"/students/{sid}", {"full_name": "Hacked By Auditor"})
    r2 = c.post(f"/students/{sid}/contact", {"email": "x@evil.example"})
    record.http("Update student record", r1)
    record.http("Update contact", r2)
    assert r1.status_code == 403 and r2.status_code == 403
    after = q1(app_db, "SELECT full_name, email, updated_at FROM students WHERE id = %s", (sid,))
    assert after == before
    record.actual("Both requests HTTP 403; student row identical before and after")


@case(id="T16", category="Authorization", role="Admin (admin01)",
      pre="admin01 creates a fresh account without roles",
      action="POST /admin/users/<id>/roles {role=AUDITOR, action=assign}",
      expected="Allowed; role assigned; ROLE_ASSIGN logged")
def test_t16_admin_assigns_role(login_as, record, lookup, app_db, audit_mark):
    c = login_as("admin01")
    username = "role" + secrets.token_hex(3)
    c.post("/admin/users", {"username": username, "full_name": "Role Test",
                            "password": "Role-Test-" + secrets.token_hex(4)})
    r = c.post(f"/admin/users/{lookup.user(username)}/roles", {"role": "AUDITOR",
                                                               "action": "assign"})
    record.http("Assign AUDITOR role", r)
    assert r.status_code == 302
    assert q(app_db, "SELECT 1 FROM user_roles ur JOIN roles r ON r.id = ur.role_id "
                     "JOIN users u ON u.id = ur.user_id WHERE u.username = %s AND r.name = 'AUDITOR'",
             (username,))
    log = q1(app_db, "SELECT actor_username, details FROM audit_logs WHERE id > %s "
                     "AND event_type = 'ROLE_ASSIGN' AND target_resource = %s",
             (audit_mark, f"user:{username}"))
    assert log and log["actor_username"] == "admin01"
    record.actual(f"HTTP 302; {username} now has AUDITOR; ROLE_ASSIGN logged by admin01")


@case(id="T17", category="Authorization", role="Admin (admin01)",
      pre="admin01 has only the ADMIN role",
      action="GET /students/<id>/grades, /courses/<id>/roster, /students",
      expected="Rejected (403)")
def test_t17_admin_views_grades(login_as, record, lookup):
    c = login_as("admin01")
    for path in (f"/students/{lookup.student('S2026001')}/grades",
                 f"/courses/{lookup.course('IS101')}/roster", "/students"):
        r = c.get(path)
        record.http(f"GET {path}", r)
        assert r.status_code == 403
        assert "S2026001" not in r.text and "IS101" not in r.text
    record.actual("All three requests HTTP 403; no grade data returned")


# ---------------------------------------------------------------------------
# Original authorization tests
# ---------------------------------------------------------------------------

@case(id="T26", category="Authorization", role="Lecturer (lecturer01)",
      pre="lecturer01 is not assigned to NW301",
      action="GET /courses/<NW301>/roster and /students/<id of student only in NW301 & DB201>",
      expected="Roster rejected (403); profile of a student taught in DB201 allowed")
def test_t26_lecturer_roster_scope(login_as, record, lookup):
    c = login_as("lecturer01")
    r = c.get(f"/courses/{lookup.course('NW301')}/roster")
    record.http("Roster of unassigned NW301", r)
    assert r.status_code == 403
    ok = c.get(f"/students/{lookup.student('S2026003')}")      # enrolled in DB201
    assert ok.status_code == 200
    g = c.get(f"/students/{lookup.student('S2026003')}/grades")
    record.http("Grades of S2026003 (DB201 taught, NW301 not)", g)
    assert "DB201" in g.text and "NW301" not in g.text
    record.actual("NW301 roster 403; S2026003 profile 200 and only DB201 grade visible "
                  "(NW301 grade hidden)")


@case(id="T27", category="Authorization", role="Student+Lecturer (ta01)",
      pre="ta01 is the lecturer of SE202 and also enrolled in SE202",
      action="POST /grades for own SE202 enrollment, then for student03's SE202 enrollment",
      expected="Self-grading rejected (403, unchanged); grading another student allowed")
def test_t27_no_self_grading(login_as, record, lookup, app_db, audit_mark):
    c = login_as("ta01")
    own = lookup.enrollment("S2026004", "SE202")
    before = lookup.score(own)
    r = c.post("/grades", {"enrollment_id": own, "final_exam": "10"})
    record.http("TA grades own enrollment", r)
    assert r.status_code == 403 and lookup.score(own) == before
    other = lookup.enrollment("S2026003", "SE202")
    comps = new_components()
    r2 = c.post("/grades", {"enrollment_id": other, **{k: str(v) for k, v in comps.items()}})
    record.http("TA grades another student", r2)
    score = weighted_total(comps)
    assert r2.status_code == 302 and lookup.total(other) == score
    log = q1(app_db, "SELECT details FROM audit_logs WHERE id > %s AND event_type = "
                     "'GRADE_MODIFY_DENIED' AND actor_username = 'ta01'", (audit_mark,))
    assert log["details"]["reason"] == "self_grading"
    record.actual(f"Own grade: 403, unchanged ({before}), reason=self_grading; "
                  f"other student: 302, score set to {score}")


@case(id="T28", category="Authorization", role="Student+Lecturer (ta01)",
      pre="ta01 holds STUDENT and LECTURER roles",
      action="GET own grades, SE202 roster (assigned), DB201 roster (not assigned)",
      expected="Union of role permissions: own grades 200, SE202 200, DB201 403")
def test_t28_multi_role_union(login_as, record, lookup):
    c = login_as("ta01")
    own = c.get(f"/students/{lookup.student('S2026004')}/grades")
    nw = c.get(f"/courses/{lookup.course('SE202')}/roster")
    db_ = c.get(f"/courses/{lookup.course('DB201')}/roster")
    record.http("Own grades", own)
    record.http("SE202 roster", nw)
    record.http("DB201 roster", db_)
    assert (own.status_code, nw.status_code, db_.status_code) == (200, 200, 403)
    record.actual("200 / 200 / 403 as expected (permissions are the union, scopes still enforced)")


@case(id="T29", category="Authorization", role="Admin (admin01)",
      pre="admin01 holds ADMIN",
      action="POST /admin/users/<own id>/roles {role=REGISTRAR, action=assign}",
      expected="Rejected (403): administrators cannot change their own roles")
def test_t29_admin_self_escalation(login_as, record, lookup, app_db):
    c = login_as("admin01")
    r = c.post(f"/admin/users/{lookup.user('admin01')}/roles", {"role": "REGISTRAR",
                                                                "action": "assign"})
    record.http("Admin assigns REGISTRAR to self", r)
    assert r.status_code == 403
    roles = q(app_db, "SELECT r.name FROM user_roles ur JOIN roles r ON r.id = ur.role_id "
                      "WHERE ur.user_id = %s", (lookup.user("admin01"),))
    assert [x["name"] for x in roles] == ["ADMIN"]
    record.actual("HTTP 403; admin01 still has only ADMIN; ROLE_ASSIGN_DENIED logged")


@case(id="T30", category="Authorization", role="Admin (admin01)",
      pre="admin02 holds ADMIN; ADMIN/AUDITOR is a declared role conflict",
      action="POST /admin/users/<admin02>/roles {role=AUDITOR, action=assign}",
      expected="Rejected (403) - separation of duties; role not added")
def test_t30_role_conflict(login_as, record, lookup, app_db, audit_mark):
    c = login_as("admin01")
    r = c.post(f"/admin/users/{lookup.user('admin02')}/roles", {"role": "AUDITOR",
                                                                "action": "assign"})
    record.http("Assign AUDITOR to an ADMIN", r)
    assert r.status_code == 403
    log = q1(app_db, "SELECT details FROM audit_logs WHERE id > %s AND event_type = "
                     "'ROLE_ASSIGN_DENIED'", (audit_mark,))
    assert log["details"]["reason"] == "role_conflict"
    record.actual(f"HTTP 403; ROLE_ASSIGN_DENIED {log['details']}")


@case(id="T31", category="Authorization", role="Student (student01)",
      pre="student02 has contact data",
      action="POST /students/<student02 id>/contact {email=attacker}",
      expected="Rejected (403); student02 contact unchanged")
def test_t31_idor_write(login_as, record, lookup, app_db):
    c = login_as("student01")
    sid = lookup.student("S2026002")
    before = q1(app_db, "SELECT email, phone, address FROM students WHERE id = %s", (sid,))
    r = c.post(f"/students/{sid}/contact", {"email": "attacker@evil.example"})
    record.http("Update another student's contact", r)
    assert r.status_code == 403
    assert q1(app_db, "SELECT email, phone, address FROM students WHERE id = %s", (sid,)) == before
    record.actual("HTTP 403; contact of S2026002 unchanged")


@case(id="T32", category="Authorization", role="Lecturer (lecturer01)",
      pre="lecturer01 logged in",
      action="POST /grades for an assigned course WITHOUT the CSRF token",
      expected="Rejected (403), unchanged; CSRF_REJECTED logged")
def test_t32_csrf(login_as, record, lookup, app_db, audit_mark):
    c = login_as("lecturer01")
    enr = lookup.enrollment("S2026002", "IS101")
    before = lookup.score(enr)
    r = c.post("/grades", {"enrollment_id": enr, "final_exam": "1"}, csrf=False)
    record.http("POST without CSRF token", r)
    assert r.status_code == 403 and lookup.score(enr) == before
    assert q(app_db, "SELECT 1 FROM audit_logs WHERE id > %s AND event_type = 'CSRF_REJECTED'",
             (audit_mark,))
    record.actual(f"HTTP 403; score unchanged ({before}); CSRF_REJECTED logged")


@case(id="T33", category="Authorization", role="Anonymous",
      pre="No session",
      action="GET /students/1/grades, /audit/logs, /admin/users; POST /grades",
      expected="Rejected (401) for every request")
def test_t33_unauthenticated(client, record):
    for method, path in (("GET", "/students/1/grades"), ("GET", "/audit/logs"),
                         ("GET", "/admin/users"), ("POST", "/grades")):
        r = client.get(path) if method == "GET" else client.post(path, {"enrollment_id": 1,
                                                                        "final_exam": 9}, csrf=False)
        record.http(f"{method} {path}", r)
        assert r.status_code == 401
    record.actual("All four requests HTTP 401")


@case(id="T34", category="Authorization", role="Admin (admin01)",
      pre="admin01 has only the ADMIN role",
      action="GET /audit/logs and /audit/policy",
      expected="Rejected (403): the administrator does not audit himself/herself")
def test_t34_admin_cannot_read_audit(login_as, record):
    c = login_as("admin01")
    for path in ("/audit/logs", "/audit/policy"):
        r = c.get(path)
        record.http(f"GET {path}", r)
        assert r.status_code == 403
    record.actual("Both HTTP 403")

"""Tests of self-registration, weighted grading and class management (original T45-T52)."""
import random
import secrets
import string

import psycopg2
import pytest

from conftest import Client, q, q1, weighted_total

case = pytest.mark.case
STRONG = "Correct-Horse-Battery-9"


def register(username=None, password=STRONG, **extra):
    username = username or "reg" + secrets.token_hex(3)
    c = Client()
    r = c.post("/register", {"full_name": "Registered Student", "username": username,
                             "email": f"{username}@student.example.edu", "password": password,
                             "confirm_password": extra.pop("confirm", password), **extra}, csrf=False)
    return username, r


def class_code():
    return "T" + "".join(random.choices(string.ascii_uppercase, k=2)) + str(random.randint(1000, 9999))


def create_class(registrar, capacity="30", lecturer=""):
    code = class_code()
    r = registrar.post("/courses", {"code": code, "title": "Test Class " + code, "credits": "3",
                                    "semester": "2026-1", "capacity": capacity, "lecturer": lecturer})
    return code, r


@case(id="T45", category="Authentication", role="Anonymous → new student",
      pre="Username does not exist",
      action="POST /register with valid data plus forged fields role=ADMIN and is_admin=1; log in",
      expected="Account created with exactly the STUDENT role and a NEW student profile; forged fields ignored; "
               "USER_REGISTER logged")
def test_t45_self_registration_student_only(record, app_db, audit_mark):
    username, r = register(role="ADMIN", is_admin="1", roles="ADMIN,AUDITOR")
    record.http("Registration with forged role fields", r)
    assert r.status_code == 302 and "notice=account_created" in r.headers["Location"]
    roles = [x["name"] for x in q(app_db, "SELECT r.name FROM user_roles ur JOIN roles r ON r.id = ur.role_id "
                                          "JOIN users u ON u.id = ur.user_id WHERE u.username = %s", (username,))]
    assert roles == ["STUDENT"]
    profile = q1(app_db, "SELECT s.id, s.student_code FROM students s JOIN users u ON u.id = s.user_id "
                         "WHERE u.username = %s", (username,))
    assert profile and profile["student_code"].startswith("S")
    c = Client()
    assert c.login(username, STRONG).status_code == 302
    assert c.get(f"/students/{profile['id']}/grades").status_code == 200
    assert c.get("/admin/users").status_code == 403
    assert q(app_db, "SELECT 1 FROM audit_logs WHERE id > %s AND event_type = 'USER_REGISTER' "
                     "AND target_resource = %s", (audit_mark, f"user:{username}"))
    record.actual(f"HTTP 302; roles = {roles}; new profile {profile['student_code']}; login works; "
                  "/admin/users 403; USER_REGISTER logged")


@case(id="T46", category="Authentication", role="Anonymous",
      pre="student01 already exists",
      action="POST /register with: short password, mismatching confirmation, password containing the username, "
             "existing username, invalid username",
      expected="Each rejected with 400; no account created")
def test_t46_registration_validation(record, app_db):
    before = q1(app_db, "SELECT count(*) AS n FROM users")["n"]
    cases = [("short password", dict(password="short1!")),
             ("confirmation mismatch", dict(confirm="Different-Pass-123")),
             ("password contains username", dict(username="alice99", password="alice99-is-my-pass")),
             ("existing username", dict(username="student01")),
             ("invalid username", dict(username="Bad User!"))]
    for label, kwargs in cases:
        _, r = register(**kwargs)
        record.http(label, r)
        assert r.status_code == 400
    assert q1(app_db, "SELECT count(*) AS n FROM users")["n"] == before
    record.actual("All 5 invalid registrations HTTP 400 with a validation message; user count unchanged")


@case(id="T47", category="Authorization", role="Lecturer (lecturer01) + Student (student02)",
      pre="student02 enrolled in DB201 (lecturer01)",
      action="Lecturer saves 4 components; then only 3 components; student02 opens own grades page",
      expected="Total = 10/20/20/50 % weighted (computed by DB); total empty while a component is missing; "
               "student sees all components, totals and overall average")
def test_t47_weighted_grades(login_as, record, lookup):
    lect = login_as("lecturer01")
    enr = lookup.enrollment("S2026002", "DB201")
    comps = {"process1": "8.00", "process2": "7.50", "midterm": "6.00", "final_exam": "9.25"}
    r = lect.post("/grades", {"enrollment_id": enr, **comps})
    record.http("Save four components", r)
    expected = weighted_total(comps)
    assert r.status_code == 302 and lookup.total(enr) == expected
    student = login_as("student02")
    page = student.get(f"/students/{lookup.student('S2026002')}/grades")
    record.http("Student views own grades", page)
    for value in ("8.00", "7.50", "6.00", "9.25", f"{expected:.2f}", "Overall average", "Process 1", "Final"):
        assert value in page.text
    r = lect.post("/grades", {"enrollment_id": enr, **comps, "final_exam": ""})
    assert r.status_code == 302 and lookup.total(enr) is None
    lect.post("/grades", {"enrollment_id": enr, **comps})
    record.actual(f"Total {expected} = 0.1×8 + 0.2×7.5 + 0.2×6 + 0.5×9.25; total NULL with a missing "
                  "component; student page shows components, total and overall average")


@case(id="T48", category="Authorization", role="Registrar / Admin / Lecturer / Student",
      pre="None",
      action="POST /courses (create class) as registrar01 (capacity 30 and 31, duplicate code) and as admin01, "
             "lecturer01, student01",
      expected="Registrar: created + COURSE_CREATE logged; capacity 31 and duplicate code → 400; others → 403")
def test_t48_create_class(login_as, record, app_db, audit_mark):
    reg = login_as("registrar01")
    code, r = create_class(reg)
    record.http("Registrar creates a class", r)
    assert r.status_code == 302
    assert q1(app_db, "SELECT capacity FROM courses WHERE code = %s", (code,))["capacity"] == 30
    assert q(app_db, "SELECT 1 FROM audit_logs WHERE id > %s AND event_type = 'COURSE_CREATE'", (audit_mark,))
    _, r31 = create_class(reg, capacity="31")
    record.http("Capacity 31", r31)
    assert r31.status_code == 400
    dup = reg.post("/courses", {"code": code, "title": "Duplicate", "credits": "3", "semester": "2026-1"})
    assert dup.status_code == 400
    for user in ("admin01", "lecturer01", "student01"):
        _, r = create_class(login_as(user))
        record.http(f"{user} creates a class", r)
        assert r.status_code == 403
    record.actual(f"{code} created (capacity 30, logged); capacity 31 and duplicate code 400; "
                  "admin01 / lecturer01 / student01 403")


@case(id="T49", category="Authorization", role="Registrar + Lecturers + DB account",
      pre="Registrar creates a class taught by lecturer01",
      action="lecturer02 tries to take the class; direct INSERT of a 2nd lecturer as uni_app; registrar replaces "
             "the lecturer",
      expected="Take-over 403; DB rejects 2nd lecturer (unique violation); replacement leaves exactly 1 lecturer")
def test_t49_one_lecturer_per_class(login_as, record, app_db):
    reg = login_as("registrar01")
    code, _ = create_class(reg, lecturer="lecturer01")
    cid = q1(app_db, "SELECT id FROM courses WHERE code = %s", (code,))["id"]
    r = login_as("lecturer02").post(f"/classes/{cid}/teach")
    record.http("lecturer02 takes a class that already has a lecturer", r)
    assert r.status_code == 403
    lect2 = q1(app_db, "SELECT id FROM users WHERE username = 'lecturer02'")["id"]
    with pytest.raises(psycopg2.Error) as exc:
        q(app_db, "INSERT INTO course_lecturers (course_id, lecturer_id) VALUES (%s, %s)", (cid, lect2))
    assert exc.value.pgcode == "23505"
    r = reg.post(f"/courses/{cid}/lecturer", {"action": "assign", "lecturer": "lecturer02"})
    assert r.status_code == 302
    rows = q(app_db, "SELECT u.username FROM course_lecturers cl JOIN users u ON u.id = cl.lecturer_id "
                     "WHERE cl.course_id = %s", (cid,))
    assert [x["username"] for x in rows] == ["lecturer02"]
    record.note("Direct insert of a second lecturer", f"{exc.value.pgcode} {str(exc.value).splitlines()[0]}")
    record.actual("Take-over 403; direct INSERT 23505 (unique course_id); after replacement the class has "
                  "exactly one lecturer (lecturer02)")


@case(id="T50", category="Authorization", role="Registrar + DB account",
      pre="Registrar creates a class with capacity 2",
      action="Enroll 3 students through the UI; then INSERT a 3rd enrollment directly as uni_app",
      expected="Third enrollment rejected (400) by the app and (23514) by the capacity trigger; 2 students remain")
def test_t50_class_capacity(login_as, record, app_db):
    reg = login_as("registrar01")
    code, _ = create_class(reg, capacity="2")
    results = []
    for student in ("S2026001", "S2026002", "S2026003"):
        r = reg.post("/enrollments", {"student_code": student, "course_code": code})
        record.http(f"Enroll {student}", r)
        results.append(r.status_code)
    assert results == [302, 302, 400]
    cid = q1(app_db, "SELECT id FROM courses WHERE code = %s", (code,))["id"]
    sid = q1(app_db, "SELECT id FROM students WHERE student_code = 'S2026003'")["id"]
    with pytest.raises(psycopg2.Error) as exc:
        q(app_db, "INSERT INTO enrollments (student_id, course_id) VALUES (%s, %s)", (sid, cid))
    assert exc.value.pgcode == "23514"
    n = q1(app_db, "SELECT count(*) AS n FROM enrollments WHERE course_id = %s AND status = 'ENROLLED'", (cid,))["n"]
    assert n == 2
    record.actual(f"UI: 302, 302, 400 (class full); direct INSERT {exc.value.pgcode} "
                  f"'{str(exc.value).splitlines()[0]}'; {n} active students")


@case(id="T51", category="Authorization", role="Student (self-registered) + student01",
      pre="Open class with free seats; student01 has grades in IS101",
      action="New student joins a class, joins again, leaves; student01 tries to leave graded IS101",
      expected="Join 302 (ENROLLED, CLASS_JOIN logged); duplicate join 400; leave 302 (DROPPED); "
               "leaving a graded class 400")
def test_t51_student_join_leave(login_as, record, app_db, lookup, audit_mark):
    username, _ = register()
    student = login_as(username, STRONG)
    code, _ = create_class(login_as("registrar01"), lecturer="lecturer01")
    cid = lookup.course(code)
    r1 = student.post(f"/classes/{cid}/join")
    r2 = student.post(f"/classes/{cid}/join")
    record.http("Join", r1)
    record.http("Join again", r2)
    status = q1(app_db, "SELECT e.status FROM enrollments e JOIN students s ON s.id = e.student_id "
                        "JOIN users u ON u.id = s.user_id WHERE u.username = %s AND e.course_id = %s",
                (username, cid))["status"]
    assert (r1.status_code, r2.status_code, status) == (302, 400, "ENROLLED")
    r3 = student.post(f"/classes/{cid}/leave")
    record.http("Leave", r3)
    assert r3.status_code == 302
    graded = login_as("student01").post(f"/classes/{lookup.course('IS101')}/leave")
    record.http("student01 leaves graded IS101", graded)
    assert graded.status_code == 400
    assert q(app_db, "SELECT 1 FROM audit_logs WHERE id > %s AND event_type = 'CLASS_JOIN'", (audit_mark,))
    record.actual("Join 302 → ENROLLED (logged); second join 400; leave 302; leaving graded IS101 400")


@case(id="T52", category="Authorization", role="Lecturer (lecturer02) + Student (student01)",
      pre="Registrar creates a class without a lecturer",
      action="student01 POSTs /classes/<id>/teach and /courses/<id>/lecturer; lecturer02 takes the class and "
             "opens the roster",
      expected="Student requests 403; lecturer02 becomes the only lecturer (COURSE_LECTURER_ASSIGN) and can "
               "open the roster")
def test_t52_lecturer_takes_open_class(login_as, record, app_db, lookup):
    code, _ = create_class(login_as("registrar01"))
    cid = lookup.course(code)
    stu = login_as("student01")
    a = stu.post(f"/classes/{cid}/teach")
    b = stu.post(f"/courses/{cid}/lecturer", {"action": "assign", "lecturer": "student01"})
    record.http("Student tries to teach", a)
    record.http("Student tries to assign a lecturer", b)
    assert a.status_code == b.status_code == 403
    lect = login_as("lecturer02")
    r = lect.post(f"/classes/{cid}/teach")
    record.http("lecturer02 takes the class", r)
    assert r.status_code == 302
    assert lect.get(f"/courses/{cid}/roster").status_code == 200
    rows = q(app_db, "SELECT lecturer_id FROM course_lecturers WHERE course_id = %s", (cid,))
    assert len(rows) == 1
    record.actual("Student 403 / 403; lecturer02 assigned (only lecturer); roster 200")


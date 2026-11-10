"""Class locking, starting and membership rules (original T59-T62)."""
import random
import secrets
import string

import pytest

from conftest import Client, q, q1

case = pytest.mark.case
STRONG = "Correct-Horse-Battery-9"


def new_class(registrar, lecturer=""):
    code = "L" + "".join(random.choices(string.ascii_uppercase, k=2)) + str(random.randint(1000, 9999))
    r = registrar.post("/courses", {"code": code, "title": "Lock Test " + code, "credits": "3",
                                    "semester": "2026-1", "capacity": "30", "lecturer": lecturer})
    assert r.status_code == 302
    return code


def new_student():
    username = "lk" + secrets.token_hex(3)
    Client().post("/register", {"full_name": "Lock Student", "username": username,
                                "email": f"{username}@student.example.edu", "password": STRONG,
                                "confirm_password": STRONG}, csrf=False)
    return username


def status(app_db, course_id):
    return q1(app_db, "SELECT is_locked, started_at FROM courses WHERE id = %s", (course_id,))


@case(id="T59", category="Authorization", role="Lecturer (lecturer01), lecturer02, student, registrar",
      pre="Registrar creates a class taught by lecturer01",
      action="lecturer01 closes enrollment; a student tries to join; lecturer02 and the student try to change the "
             "status; lecturer01 reopens; the student joins",
      expected="Join while closed 403 (CLASS_JOIN_DENIED); status change by others 403; after reopening the join "
               "succeeds")
def test_t59_lock_blocks_join(login_as, record, lookup, app_db, audit_mark):
    code = new_class(login_as("registrar01"), lecturer="lecturer01")
    cid = lookup.course(code)
    lect = login_as("lecturer01")
    assert lect.post(f"/courses/{cid}/status", {"action": "lock"}).status_code == 302
    username = new_student()
    student = login_as(username, STRONG)
    blocked = student.post(f"/classes/{cid}/join")
    record.http("Join a closed class", blocked)
    other = login_as("lecturer02").post(f"/courses/{cid}/status", {"action": "unlock"})
    self_unlock = student.post(f"/courses/{cid}/status", {"action": "unlock"})
    record.http("Another lecturer opens enrollment", other)
    assert (blocked.status_code, other.status_code, self_unlock.status_code) == (403, 403, 403)
    assert status(app_db, cid)["is_locked"] is True
    assert lect.post(f"/courses/{cid}/status", {"action": "unlock"}).status_code == 302
    joined = student.post(f"/classes/{cid}/join")
    assert joined.status_code == 302
    assert q(app_db, "SELECT 1 FROM audit_logs WHERE id > %s AND event_type = 'CLASS_JOIN_DENIED'", (audit_mark,))
    record.actual("Closed: join 403 (logged); lecturer02 and student cannot change the status (403); reopened by "
                  "lecturer01 → join 302")


@case(id="T60", category="Authorization", role="Lecturers (lecturer01, lecturer02) + Registrar",
      pre="Two new classes: one taught by lecturer02 (not started), one by lecturer01",
      action="lecturer02 leaves the unstarted class; lecturer01 starts the other class and then tries to leave it; "
             "the registrar removes lecturer01",
      expected="Leaving before start 302; start locks the class; leaving after start 403 "
               "(CLASS_TEACH_LEAVE_DENIED); registrar removal 302")
def test_t60_start_class_keeps_lecturer(login_as, record, lookup, app_db, audit_mark):
    reg = login_as("registrar01")
    open_code = new_class(reg, lecturer="lecturer02")
    left = login_as("lecturer02").post(f"/classes/{lookup.course(open_code)}/stop-teaching")
    record.http("Lecturer leaves an unstarted class", left)
    assert left.status_code == 302
    assert not q(app_db, "SELECT 1 FROM course_lecturers WHERE course_id = %s", (lookup.course(open_code),))
    code = new_class(reg, lecturer="lecturer01")
    cid = lookup.course(code)
    lect = login_as("lecturer01")
    assert lect.post(f"/courses/{cid}/status", {"action": "start"}).status_code == 302
    st = status(app_db, cid)
    assert st["is_locked"] is True and st["started_at"] is not None
    leave = lect.post(f"/classes/{cid}/stop-teaching")
    record.http("Lecturer leaves a started class", leave)
    assert leave.status_code == 403
    assert q(app_db, "SELECT 1 FROM course_lecturers WHERE course_id = %s", (cid,))
    removed = reg.post(f"/courses/{cid}/lecturer", {"action": "remove"})
    assert removed.status_code == 302
    assert not q(app_db, "SELECT 1 FROM course_lecturers WHERE course_id = %s", (cid,))
    assert q(app_db, "SELECT 1 FROM audit_logs WHERE id > %s AND event_type = 'CLASS_TEACH_LEAVE_DENIED'",
             (audit_mark,))
    record.actual("Leave before start 302; start → locked + started; leave after start 403 (logged), lecturer kept; "
                  "registrar removes the lecturer 302")


@case(id="T61", category="Authorization", role="Lecturer (lecturer01), lecturer02",
      pre="New class taught by lecturer01 with one enrolled student",
      action="lecturer01 removes the student before the start; starts the class; removes the student; lecturer02 "
             "tries to remove a student of this class",
      expected="Before start 403; after start 302 (DROPPED); another lecturer 403")
def test_t61_lecturer_removes_student_after_start(login_as, record, lookup, app_db):
    reg = login_as("registrar01")
    code = new_class(reg, lecturer="lecturer01")
    cid = lookup.course(code)
    for student in ("S2026002", "S2026003"):
        assert reg.post("/enrollments", {"student_code": student, "course_code": code}).status_code == 302
    e1 = q1(app_db, "SELECT e.id FROM enrollments e JOIN students s ON s.id = e.student_id "
                    "WHERE e.course_id = %s AND s.student_code = 'S2026002'", (cid,))["id"]
    e2 = q1(app_db, "SELECT e.id FROM enrollments e JOIN students s ON s.id = e.student_id "
                    "WHERE e.course_id = %s AND s.student_code = 'S2026003'", (cid,))["id"]
    lect = login_as("lecturer01")
    early = lect.post(f"/enrollments/{e1}/drop", {"return_to": "course"})
    record.http("Remove before start", early)
    assert early.status_code == 403
    lect.post(f"/courses/{cid}/status", {"action": "start"})
    later = lect.post(f"/enrollments/{e1}/drop", {"return_to": "course"})
    record.http("Remove after start", later)
    assert later.status_code == 302
    assert q1(app_db, "SELECT status FROM enrollments WHERE id = %s", (e1,))["status"] == "DROPPED"
    foreign = login_as("lecturer02").post(f"/enrollments/{e2}/drop", {"return_to": "course"})
    record.http("Another lecturer removes a student", foreign)
    assert foreign.status_code == 403
    assert q1(app_db, "SELECT status FROM enrollments WHERE id = %s", (e2,))["status"] == "ENROLLED"
    record.actual("Before start 403; after start 302 → DROPPED; lecturer02 403, enrollment unchanged")


@case(id="T62", category="Authorization", role="Registrar (registrar01) + Lecturer (lecturer01)",
      pre="New class started by lecturer01 (locked)",
      action="Registrar adds and removes a student in the started, locked class; lecturer01 reopens enrollment "
             "of the started class and closes it again",
      expected="Registrar add 302 and remove 302 despite the lock; manual reopen/close after start 302")
def test_t62_registrar_any_time_and_manual_unlock(login_as, record, lookup, app_db):
    reg = login_as("registrar01")
    code = new_class(reg, lecturer="lecturer01")
    cid = lookup.course(code)
    lect = login_as("lecturer01")
    lect.post(f"/courses/{cid}/status", {"action": "start"})
    add = reg.post("/enrollments", {"student_code": "S2026006", "course_code": code})
    record.http("Registrar adds a student to a locked class", add)
    assert add.status_code == 302
    eid = q1(app_db, "SELECT id FROM enrollments WHERE course_id = %s", (cid,))["id"]
    drop = reg.post(f"/enrollments/{eid}/drop")
    assert drop.status_code == 302
    assert lect.post(f"/courses/{cid}/status", {"action": "unlock"}).status_code == 302
    assert status(app_db, cid)["is_locked"] is False and status(app_db, cid)["started_at"] is not None
    assert lect.post(f"/courses/{cid}/status", {"action": "lock"}).status_code == 302
    assert status(app_db, cid)["is_locked"] is True
    record.actual("Registrar add 302 and remove 302 in a started, locked class; lecturer reopened (still started) "
                  "and closed enrollment again")

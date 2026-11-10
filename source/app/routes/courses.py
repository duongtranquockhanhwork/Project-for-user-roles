"""Classes (courses): catalog, creation, lecturer assignment, rosters and grading.

Rules enforced here and again in the database:
* a class has at most ONE lecturer (UNIQUE course_lecturers.course_id),
* a class holds at most its capacity (<= 30) of active students (trigger),
* grades are written only by the class's lecturer, never for the lecturer's
  own enrollment (application check + grades_guard trigger),
* the course total is computed by the database from four weighted components.
"""
from flask import Blueprint, abort, g, redirect, render_template, request, url_for

from .. import audit, db
from ..authz import (can_access_course, deny, require_any_permission, require_permission)
from ..validators import COURSE_CODE_RE, SEMESTER_RE, USERNAME_RE, ValidationError, Validator

bp = Blueprint("courses", __name__)

COMPONENTS = (("process1", "Process 1", 10), ("process2", "Process 2", 20),
              ("midterm", "Midterm", 20), ("final_exam", "Final exam", 50))
MAX_CAPACITY = 30


def _lecturers():
    return db.query_all(
        "SELECT u.id, u.username, u.full_name FROM users u JOIN user_roles ur ON ur.user_id = u.id "
        "  JOIN roles r ON r.id = ur.role_id AND r.name = 'LECTURER' WHERE u.is_active ORDER BY u.full_name")


def _course(course_id):
    return db.query_one(
        "SELECT c.id, c.code, c.title, c.credits, c.semester, c.capacity, cl.lecturer_id, "
        "       u.full_name AS lecturer_name, u.username AS lecturer_username, "
        "       (SELECT count(*) FROM enrollments e WHERE e.course_id = c.id AND e.status = 'ENROLLED') AS enrolled "
        "  FROM courses c LEFT JOIN course_lecturers cl ON cl.course_id = c.id "
        "  LEFT JOIN users u ON u.id = cl.lecturer_id WHERE c.id = %s", (course_id,))


# ---------------------------------------------------------------------------
# Course list (lecturer: assigned, registrar: all) and class creation
# ---------------------------------------------------------------------------

@bp.get("/courses")
@require_permission("course.read")
def list_courses():
    sees_all = "ALL" in g.user.scopes("course.read")
    rows = db.query_all(
        "SELECT c.id, c.code, c.title, c.credits, c.semester, c.capacity, u.full_name AS lecturer_name, "
        "       (SELECT count(*) FROM enrollments e "
        "         WHERE e.course_id = c.id AND e.status = 'ENROLLED') AS enrolled "
        "  FROM courses c LEFT JOIN course_lecturers cl ON cl.course_id = c.id "
        "  LEFT JOIN users u ON u.id = cl.lecturer_id "
        " WHERE %s OR cl.lecturer_id = %s ORDER BY c.code", (sees_all, g.user.id))
    return render_template("courses.html", courses=rows)


@bp.get("/courses/new")
@require_permission("course.manage")
def new_course():
    return render_template("course_form.html", lecturers=_lecturers(), form={})


@bp.post("/courses")
@require_permission("course.manage")
def create_course():
    v = Validator(request.form)
    v.pattern("code", "Class code", COURSE_CODE_RE, transform=str.upper)
    v.text("title", "Title", 120, min_len=3)
    v.int_range("credits", "Credits", 1, 10)
    v.pattern("semester", "Semester", SEMESTER_RE)
    v.int_range("capacity", "Capacity", 1, MAX_CAPACITY, default=MAX_CAPACITY)
    v.pattern("lecturer", "Lecturer", USERNAME_RE, required=False, transform=str.lower)
    data = v.done()
    if db.query_one("SELECT 1 FROM courses WHERE code = %s", (data["code"],)):
        raise ValidationError(["A class with this code already exists."])
    lecturer = None
    if data["lecturer"]:
        lecturer = next((x for x in _lecturers() if x["username"] == data["lecturer"]), None)
        if lecturer is None:
            raise ValidationError(["The selected lecturer is not an active LECTURER."])
    course = db.query_one(
        "INSERT INTO courses (code, title, credits, semester, capacity, created_by) "
        "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        (data["code"], data["title"], data["credits"], data["semester"], data["capacity"], g.user.id))
    if lecturer:
        db.execute("INSERT INTO course_lecturers (course_id, lecturer_id, assigned_by) VALUES (%s, %s, %s)",
                   (course["id"], lecturer["id"], g.user.id))
    audit.log_event("COURSE_CREATE", audit.SUCCESS, f"course:{course['id']}",
                    {"code": data["code"], "capacity": data["capacity"],
                     "lecturer": lecturer["username"] if lecturer else None}, in_request_tx=True)
    db.commit()
    return redirect(url_for("courses.roster", course_id=course["id"], notice="course_created"))


@bp.post("/courses/<int:course_id>/lecturer")
@require_permission("course.manage")
def set_lecturer(course_id):
    """Registrar assigns, replaces or removes the (single) lecturer of a class."""
    course = _course(course_id) or abort(404)
    v = Validator(request.form)
    v.choice("action", "Action", ("assign", "remove"))
    v.pattern("lecturer", "Lecturer", USERNAME_RE, required=False, transform=str.lower)
    data = v.done()
    target = f"course:{course_id}/lecturer"
    if data["action"] == "remove":
        if course["lecturer_id"] is None:
            raise ValidationError(["This class has no lecturer."])
        db.execute("DELETE FROM course_lecturers WHERE course_id = %s", (course_id,))
        audit.log_event("COURSE_LECTURER_REMOVE", audit.SUCCESS, target,
                        {"course": course["code"], "lecturer": course["lecturer_username"]}, in_request_tx=True)
        notice = "lecturer_removed"
    else:
        lecturer = next((x for x in _lecturers() if x["username"] == data["lecturer"]), None)
        if lecturer is None:
            raise ValidationError(["The selected lecturer is not an active LECTURER."])
        # One lecturer per class: the previous assignment is replaced in the same transaction.
        db.execute("DELETE FROM course_lecturers WHERE course_id = %s", (course_id,))
        db.execute("INSERT INTO course_lecturers (course_id, lecturer_id, assigned_by) VALUES (%s, %s, %s)",
                   (course_id, lecturer["id"], g.user.id))
        audit.log_event("COURSE_LECTURER_ASSIGN", audit.SUCCESS, target,
                        {"course": course["code"], "lecturer": lecturer["username"],
                         "replaced": course["lecturer_username"]}, in_request_tx=True)
        notice = "lecturer_assigned"
    db.commit()
    return redirect(url_for("courses.roster", course_id=course_id, notice=notice))


# ---------------------------------------------------------------------------
# Roster and grading
# ---------------------------------------------------------------------------

@bp.get("/courses/<int:course_id>/roster")
@require_permission("roster.read")
def roster(course_id):
    course = _course(course_id)
    if course is None or not can_access_course("roster.read", course_id):
        deny("RECORD_ACCESS_DENIED", f"course:{course_id}/roster",
             {"permission": "roster.read"})
    show_grades = can_access_course("grade.read", course_id)
    can_grade = can_access_course("grade.write", course_id)
    rows = db.query_all(
        "SELECT e.id AS enrollment_id, e.status, s.id AS student_id, s.student_code, "
        "       s.full_name, s.user_id, gr.process1, gr.process2, gr.midterm, gr.final_exam, gr.score "
        "  FROM enrollments e "
        "  JOIN students s ON s.id = e.student_id "
        "  LEFT JOIN grades gr ON gr.enrollment_id = e.id "
        " WHERE e.course_id = %s ORDER BY e.status, s.student_code", (course_id,))
    manage = g.user.has("course.manage")
    return render_template("roster.html", course=course, rows=rows, show_grades=show_grades,
                           can_grade=can_grade, manage=manage, components=COMPONENTS,
                           can_enroll=g.user.has("enrollment.manage"),
                           lecturers=_lecturers() if manage else [])


@bp.post("/grades")
@require_permission("grade.write", deny_event="GRADE_MODIFY_DENIED")
def save_grade():
    v = Validator(request.form)
    v.positive_int("enrollment_id", "Enrollment")
    for name, label, _ in COMPONENTS:
        v.optional_score(name, label)
    data = v.done()
    if all(data[name] is None for name, _, _ in COMPONENTS):
        raise ValidationError(["Enter at least one grade component."])
    enrollment_id = data["enrollment_id"]
    target = f"enrollment:{enrollment_id}/grade"

    enrollment = db.query_one(
        "SELECT e.id, e.course_id, e.status, s.user_id AS student_user_id, s.student_code, "
        "       c.code AS course_code "
        "  FROM enrollments e JOIN students s ON s.id = e.student_id "
        "  JOIN courses c ON c.id = e.course_id WHERE e.id = %s", (enrollment_id,))
    if enrollment is None:
        deny("GRADE_MODIFY_DENIED", target, {"reason": "unknown_enrollment"})
    if not can_access_course("grade.write", enrollment["course_id"]):
        deny("GRADE_MODIFY_DENIED", target,
             {"reason": "course_not_assigned", "course": enrollment["course_code"]})
    if enrollment["student_user_id"] == g.user.id:
        deny("GRADE_MODIFY_DENIED", target,
             {"reason": "self_grading", "course": enrollment["course_code"]})
    if enrollment["status"] != "ENROLLED":
        raise ValidationError(["Grades can only be recorded for active enrollments."])

    values = [data[name] for name, _, _ in COMPONENTS]
    existing = db.query_one(
        "SELECT id, process1, process2, midterm, final_exam, score FROM grades "
        "WHERE enrollment_id = %s FOR UPDATE", (enrollment_id,))
    if existing:
        db.execute("UPDATE grades SET process1 = %s, process2 = %s, midterm = %s, final_exam = %s, "
                   "       updated_by = %s WHERE id = %s", (*values, g.user.id, existing["id"]))
        event = "GRADE_UPDATE"
        details = {f"old_{n}": str(existing[n]) for n, _, _ in COMPONENTS if existing[n] != data[n]}
    else:
        db.execute("INSERT INTO grades (enrollment_id, process1, process2, midterm, final_exam, "
                   "created_by, updated_by) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                   (enrollment_id, *values, g.user.id, g.user.id))
        event, details = "GRADE_CREATE", {}
    total = db.query_one("SELECT score FROM grades WHERE enrollment_id = %s", (enrollment_id,))["score"]
    details.update({n: (str(data[n]) if data[n] is not None else None) for n, _, _ in COMPONENTS})
    details.update({"total": str(total) if total is not None else None,
                    "course": enrollment["course_code"], "student_code": enrollment["student_code"]})
    audit.log_event(event, audit.SUCCESS, target, details, in_request_tx=True)
    db.commit()
    return redirect(url_for("courses.roster", course_id=enrollment["course_id"], notice="grade_saved"))


# ---------------------------------------------------------------------------
# Class catalog: students join / leave, lecturers take an unassigned class
# ---------------------------------------------------------------------------

@bp.get("/classes")
@require_any_permission("class.join", "class.teach")
def catalog():
    rows = db.query_all(
        "SELECT c.id, c.code, c.title, c.credits, c.semester, c.capacity, cl.lecturer_id, "
        "       u.full_name AS lecturer_name, "
        "       (SELECT count(*) FROM enrollments e WHERE e.course_id = c.id AND e.status = 'ENROLLED') AS enrolled, "
        "       (SELECT e.status FROM enrollments e WHERE e.course_id = c.id AND e.student_id = %s) AS my_status, "
        "       (SELECT count(*) FROM enrollments e JOIN grades gr ON gr.enrollment_id = e.id "
        "         WHERE e.course_id = c.id AND e.student_id = %s) AS my_graded "
        "  FROM courses c LEFT JOIN course_lecturers cl ON cl.course_id = c.id "
        "  LEFT JOIN users u ON u.id = cl.lecturer_id ORDER BY c.code",
        (g.user.student_id or 0, g.user.student_id or 0))
    return render_template("classes.html", classes=rows,
                           can_join=g.user.has("class.join") and g.user.student_id is not None,
                           can_teach=g.user.has("class.teach"))


@bp.post("/classes/<int:course_id>/join")
@require_permission("class.join")
def join_class(course_id):
    course = _course(course_id) or abort(404)
    if g.user.student_id is None:
        raise ValidationError(["Your account has no student profile."])
    if course["lecturer_id"] == g.user.id:
        deny("CLASS_JOIN_DENIED", f"course:{course_id}", {"reason": "teaches_this_class"})
    existing = db.query_one("SELECT id, status FROM enrollments WHERE student_id = %s AND course_id = %s",
                            (g.user.student_id, course_id))
    if existing and existing["status"] == "ENROLLED":
        raise ValidationError(["You are already enrolled in this class."])
    if course["enrolled"] >= course["capacity"]:
        raise ValidationError([f"This class is full ({course['capacity']} students)."])
    if existing:
        db.execute("UPDATE enrollments SET status = 'ENROLLED' WHERE id = %s", (existing["id"],))
        enrollment_id = existing["id"]
    else:
        enrollment_id = db.query_one(
            "INSERT INTO enrollments (student_id, course_id, enrolled_by) VALUES (%s, %s, %s) RETURNING id",
            (g.user.student_id, course_id, g.user.id))["id"]
    audit.log_event("CLASS_JOIN", audit.SUCCESS, f"enrollment:{enrollment_id}",
                    {"course": course["code"]}, in_request_tx=True)
    db.commit()
    return redirect(url_for("courses.catalog", notice="class_joined"))


@bp.post("/classes/<int:course_id>/leave")
@require_permission("class.join")
def leave_class(course_id):
    course = _course(course_id) or abort(404)
    row = db.query_one(
        "SELECT e.id, (SELECT count(*) FROM grades gr WHERE gr.enrollment_id = e.id) AS graded "
        "  FROM enrollments e WHERE e.student_id = %s AND e.course_id = %s AND e.status = 'ENROLLED'",
        (g.user.student_id or 0, course_id))
    if row is None:
        raise ValidationError(["You are not enrolled in this class."])
    if row["graded"]:
        raise ValidationError(["You cannot leave a class in which grades have already been recorded. "
                               "Please contact the registrar."])
    db.execute("UPDATE enrollments SET status = 'DROPPED' WHERE id = %s", (row["id"],))
    audit.log_event("CLASS_LEAVE", audit.SUCCESS, f"enrollment:{row['id']}",
                    {"course": course["code"]}, in_request_tx=True)
    db.commit()
    return redirect(url_for("courses.catalog", notice="class_left"))


@bp.post("/classes/<int:course_id>/teach")
@require_permission("class.teach")
def teach_class(course_id):
    """A lecturer takes a class that has no lecturer yet (one lecturer per class)."""
    course = _course(course_id) or abort(404)
    target = f"course:{course_id}/lecturer"
    if course["lecturer_id"] is not None:
        deny("CLASS_TEACH_DENIED", target, {"reason": "class_already_has_lecturer", "course": course["code"]})
    if g.user.student_id and db.query_one(
            "SELECT 1 FROM enrollments WHERE student_id = %s AND course_id = %s AND status = 'ENROLLED'",
            (g.user.student_id, course_id)):
        deny("CLASS_TEACH_DENIED", target, {"reason": "enrolled_as_student", "course": course["code"]})
    db.execute("INSERT INTO course_lecturers (course_id, lecturer_id, assigned_by) VALUES (%s, %s, %s)",
               (course_id, g.user.id, g.user.id))
    audit.log_event("COURSE_LECTURER_ASSIGN", audit.SUCCESS, target,
                    {"course": course["code"], "lecturer": g.user.username, "self_service": True},
                    in_request_tx=True)
    db.commit()
    return redirect(url_for("courses.roster", course_id=course_id, notice="teaching_started"))

"""Enrollment management (Registrar)."""
from flask import Blueprint, abort, g, redirect, render_template, request, url_for

from .. import audit, db
from ..authz import can_access_course, deny, require_any_permission, require_permission
from ..validators import COURSE_CODE_RE, STUDENT_CODE_RE, ValidationError, Validator

bp = Blueprint("enrollments", __name__)


def _back(course_id, notice):
    """Return to the class page or to the enrollment list (fixed choices: no open redirect)."""
    if request.form.get("return_to") == "course" and course_id:
        return redirect(url_for("courses.roster", course_id=course_id, notice=notice))
    return redirect(url_for("enrollments.list_enrollments", notice=notice))


@bp.get("/enrollments")
@require_permission("enrollment.manage")
def list_enrollments():
    rows = db.query_all(
        "SELECT e.id, s.student_code, s.full_name, c.code AS course_code, e.status, "
        "       e.enrolled_at "
        "  FROM enrollments e JOIN students s ON s.id = e.student_id "
        "  JOIN courses c ON c.id = e.course_id "
        " ORDER BY c.code, s.student_code")
    courses = db.query_all("SELECT code, title FROM courses ORDER BY code")
    return render_template("enrollments.html", enrollments=rows, courses=courses)


@bp.post("/enrollments")
@require_permission("enrollment.manage")
def create_enrollment():
    v = Validator(request.form)
    v.pattern("student_code", "Student code", STUDENT_CODE_RE, transform=str.upper)
    v.pattern("course_code", "Course code", COURSE_CODE_RE, transform=str.upper)
    data = v.done()

    student = db.query_one("SELECT id FROM students WHERE student_code = %s",
                           (data["student_code"],))
    course = db.query_one(
        "SELECT c.id, c.capacity, (SELECT count(*) FROM enrollments e "
        "  WHERE e.course_id = c.id AND e.status = 'ENROLLED') AS enrolled FROM courses c WHERE c.code = %s",
        (data["course_code"],))
    if student is None or course is None:
        raise ValidationError(["Unknown student code or course code."])
    if course["enrolled"] >= course["capacity"]:
        raise ValidationError([f"This class is full ({course['capacity']} students)."])

    existing = db.query_one(
        "SELECT id, status FROM enrollments WHERE student_id = %s AND course_id = %s",
        (student["id"], course["id"]))
    if existing and existing["status"] == "ENROLLED":
        raise ValidationError(["The student is already enrolled in this course."])
    if existing:
        db.execute("UPDATE enrollments SET status = 'ENROLLED' WHERE id = %s", (existing["id"],))
        enrollment_id = existing["id"]
    else:
        enrollment_id = db.query_one(
            "INSERT INTO enrollments (student_id, course_id, enrolled_by) "
            "VALUES (%s, %s, %s) RETURNING id",
            (student["id"], course["id"], g.user.id))["id"]
    audit.log_event("ENROLLMENT_CREATE", audit.SUCCESS, f"enrollment:{enrollment_id}",
                    {"student_code": data["student_code"], "course": data["course_code"]},
                    in_request_tx=True)
    db.commit()
    return _back(course["id"], "enrollment_created")


@bp.post("/enrollments/<int:enrollment_id>/drop")
@require_any_permission("enrollment.manage", "class.remove_student", deny_event="ENROLLMENT_DROP_DENIED")
def drop_enrollment(enrollment_id):
    """Registrar: always. Lecturer: only students of their own class, and only after it has started."""
    if not g.user.has("enrollment.manage"):
        info = db.query_one(
            "SELECT e.course_id, c.started_at, s.user_id FROM enrollments e JOIN courses c ON c.id = e.course_id "
            "  JOIN students s ON s.id = e.student_id WHERE e.id = %s", (enrollment_id,))
        target = f"enrollment:{enrollment_id}"
        if info is None or not can_access_course("class.remove_student", info["course_id"]):
            deny("ENROLLMENT_DROP_DENIED", target, {"reason": "course_not_assigned"})
        if info["started_at"] is None:
            deny("ENROLLMENT_DROP_DENIED", target, {"reason": "class_not_started"})
        if info["user_id"] == g.user.id:
            deny("ENROLLMENT_DROP_DENIED", target, {"reason": "own_enrollment"})
    row = db.query_one(
        "UPDATE enrollments SET status = 'DROPPED' WHERE id = %s AND status = 'ENROLLED' "
        "RETURNING id, course_id", (enrollment_id,))
    if row is None:
        abort(404)
    audit.log_event("ENROLLMENT_DROP", audit.SUCCESS, f"enrollment:{enrollment_id}",
                    in_request_tx=True)
    db.commit()
    return _back(row["course_id"], "enrollment_dropped")


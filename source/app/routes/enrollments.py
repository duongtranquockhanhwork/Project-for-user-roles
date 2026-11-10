"""Enrollment management (Registrar)."""
from flask import Blueprint, abort, g, redirect, render_template, request, url_for

from .. import audit, db
from ..authz import require_permission
from ..validators import COURSE_CODE_RE, STUDENT_CODE_RE, ValidationError, Validator

bp = Blueprint("enrollments", __name__)


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
    course = db.query_one("SELECT id FROM courses WHERE code = %s", (data["course_code"],))
    if student is None or course is None:
        raise ValidationError(["Unknown student code or course code."])

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
    return redirect(url_for("enrollments.list_enrollments", notice="enrollment_created"))


@bp.post("/enrollments/<int:enrollment_id>/drop")
@require_permission("enrollment.manage")
def drop_enrollment(enrollment_id):
    row = db.query_one(
        "UPDATE enrollments SET status = 'DROPPED' WHERE id = %s AND status = 'ENROLLED' "
        "RETURNING id", (enrollment_id,))
    if row is None:
        abort(404)
    audit.log_event("ENROLLMENT_DROP", audit.SUCCESS, f"enrollment:{enrollment_id}",
                    in_request_tx=True)
    db.commit()
    return redirect(url_for("enrollments.list_enrollments", notice="enrollment_dropped"))


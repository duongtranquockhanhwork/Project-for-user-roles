"""Courses, course rosters and grade entry."""
from flask import Blueprint, g, redirect, render_template, request, url_for

from .. import audit, db
from ..authz import can_access_course, deny, require_permission
from ..validators import ValidationError, Validator

bp = Blueprint("courses", __name__)


@bp.get("/courses")
@require_permission("course.read")
def list_courses():
    sees_all = "ALL" in g.user.scopes("course.read")
    rows = db.query_all(
        "SELECT c.id, c.code, c.title, c.credits, c.semester, "
        "       (SELECT count(*) FROM enrollments e "
        "         WHERE e.course_id = c.id AND e.status = 'ENROLLED') AS enrolled "
        "  FROM courses c "
        " WHERE %s OR EXISTS (SELECT 1 FROM course_lecturers cl "
        "                      WHERE cl.course_id = c.id AND cl.lecturer_id = %s) "
        " ORDER BY c.code", (sees_all, g.user.id))
    return render_template("courses.html", courses=rows)


@bp.get("/courses/<int:course_id>/roster")
@require_permission("roster.read")
def roster(course_id):
    course = db.query_one("SELECT id, code, title, semester FROM courses WHERE id = %s",
                          (course_id,))
    if course is None or not can_access_course("roster.read", course_id):
        deny("RECORD_ACCESS_DENIED", f"course:{course_id}/roster",
             {"permission": "roster.read"})
    show_grades = can_access_course("grade.read", course_id)
    can_grade = can_access_course("grade.write", course_id)
    rows = db.query_all(
        "SELECT e.id AS enrollment_id, e.status, s.id AS student_id, s.student_code, "
        "       s.full_name, s.user_id, gr.score "
        "  FROM enrollments e "
        "  JOIN students s ON s.id = e.student_id "
        "  LEFT JOIN grades gr ON gr.enrollment_id = e.id "
        " WHERE e.course_id = %s ORDER BY s.student_code", (course_id,))
    return render_template("roster.html", course=course, rows=rows,
                           show_grades=show_grades, can_grade=can_grade)


@bp.post("/grades")
@require_permission("grade.write", deny_event="GRADE_MODIFY_DENIED")
def save_grade():
    v = Validator(request.form)
    v.positive_int("enrollment_id", "Enrollment")
    v.score("score")
    data = v.done()
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
             {"reason": "course_not_assigned", "course": enrollment["course_code"],
              "attempted_score": str(data["score"])})
    if enrollment["student_user_id"] == g.user.id:
        deny("GRADE_MODIFY_DENIED", target,
             {"reason": "self_grading", "course": enrollment["course_code"]})
    if enrollment["status"] != "ENROLLED":
        raise ValidationError(["Grades can only be recorded for active enrollments."])

    existing = db.query_one(
        "SELECT id, score FROM grades WHERE enrollment_id = %s FOR UPDATE", (enrollment_id,))
    if existing:
        db.execute("UPDATE grades SET score = %s, updated_by = %s WHERE id = %s",
                   (data["score"], g.user.id, existing["id"]))
        event, details = "GRADE_UPDATE", {"old_score": str(existing["score"])}
    else:
        db.execute("INSERT INTO grades (enrollment_id, score, created_by, updated_by) "
                   "VALUES (%s, %s, %s, %s)",
                   (enrollment_id, data["score"], g.user.id, g.user.id))
        event, details = "GRADE_CREATE", {}
    details.update({"new_score": str(data["score"]), "course": enrollment["course_code"],
                    "student_code": enrollment["student_code"]})
    audit.log_event(event, audit.SUCCESS, target, details, in_request_tx=True)
    db.commit()
    return redirect(url_for("courses.roster", course_id=enrollment["course_id"], notice="grade_saved"))

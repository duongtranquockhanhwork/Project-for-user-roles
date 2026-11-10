"""Student records: profile, contact information, enrollments and grades.

Every handler that receives a student id performs a record-level check
(`_load_student_or_deny`) in addition to the permission decorator, so changing
the id in the URL (IDOR) cannot reach another student's data.
"""
from flask import Blueprint, abort, g, redirect, render_template, request, url_for

from .. import audit, db
from ..authz import can_access_student, deny, require_permission
from ..validators import (STUDENT_CODE_RE, USERNAME_RE, ValidationError, Validator,
                          contact_fields)

bp = Blueprint("students", __name__)

_STUDENT_COLUMNS = ("s.id, s.user_id, s.student_code, s.full_name, s.date_of_birth, s.program, "
                    "s.email, s.phone, s.address, s.updated_at, u.username")


def _load_student_or_deny(student_id, permission, target_suffix=""):
    student = db.query_one(
        f"SELECT {_STUDENT_COLUMNS} FROM students s LEFT JOIN users u ON u.id = s.user_id "
        "WHERE s.id = %s", (student_id,))
    target = f"student:{student_id}{target_suffix}"
    if student is None:
        # Users without the ALL scope get the same 403 for missing and foreign
        # records, so ids cannot be enumerated.
        if "ALL" in g.user.scopes(permission):
            abort(404)
        deny("RECORD_ACCESS_DENIED", target, {"permission": permission})
    if not can_access_student(permission, student):
        deny("RECORD_ACCESS_DENIED", target,
             {"permission": permission, "method": request.method})
    return student


# ---------------------------------------------------------------------------
# Registrar: list / search / create / update
# ---------------------------------------------------------------------------

@bp.get("/students")
@require_permission("student.search")
def list_students():
    q = (request.args.get("q") or "").strip()
    if len(q) > 50:
        raise ValidationError(["Search text must be at most 50 characters."])
    # The search text is a bound parameter; LIKE wildcards are escaped.
    pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    rows = db.query_all(
        "SELECT s.id, s.student_code, s.full_name, s.program, u.username "
        "  FROM students s LEFT JOIN users u ON u.id = s.user_id "
        " WHERE s.student_code ILIKE %s ESCAPE '\\' OR s.full_name ILIKE %s ESCAPE '\\' "
        " ORDER BY s.student_code LIMIT 200", (pattern, pattern))
    return render_template("students_list.html", students=rows, q=q)


@bp.get("/students/new")
@require_permission("student.create")
def new_student():
    return render_template("student_form.html", student=None)


@bp.post("/students")
@require_permission("student.create")
def create_student():
    v = Validator(request.form)
    v.pattern("student_code", "Student code", STUDENT_CODE_RE, transform=str.upper)
    v.text("full_name", "Full name", 100)
    v.date("date_of_birth", "Date of birth")
    v.text("program", "Program", 100, required=False)
    contact_fields(v)
    v.pattern("linked_username", "Linked username", USERNAME_RE, required=False,
              transform=str.lower)
    data = v.done()

    if db.query_one("SELECT 1 FROM students WHERE student_code = %s", (data["student_code"],)):
        raise ValidationError(["Student code already exists."])

    linked_user_id = None
    if data["linked_username"]:
        account = db.query_one(
            "SELECT u.id FROM users u JOIN user_roles ur ON ur.user_id = u.id "
            "  JOIN roles r ON r.id = ur.role_id AND r.name = 'STUDENT' "
            " WHERE u.username = %s AND NOT EXISTS "
            "       (SELECT 1 FROM students s WHERE s.user_id = u.id)",
            (data["linked_username"],))
        if account is None:
            raise ValidationError(["Linked username must be an unlinked account with the STUDENT role."])
        linked_user_id = account["id"]

    row = db.query_one(
        "INSERT INTO students (user_id, student_code, full_name, date_of_birth, program, "
        "                      email, phone, address, created_by, updated_by) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (linked_user_id, data["student_code"], data["full_name"], data["date_of_birth"],
         data["program"], data["email"], data["phone"], data["address"],
         g.user.id, g.user.id))
    audit.log_event("STUDENT_CREATE", audit.SUCCESS, f"student:{row['id']}",
                    {"student_code": data["student_code"],
                     "linked_username": data["linked_username"]}, in_request_tx=True)
    db.commit()
    return redirect(url_for("students.view_student", student_id=row["id"], notice="student_created"))


@bp.get("/students/<int:student_id>/edit")
@require_permission("student.update")
def edit_student(student_id):
    student = _load_student_or_deny(student_id, "student.update")
    return render_template("student_form.html", student=student)


@bp.post("/students/<int:student_id>")
@require_permission("student.update")
def update_student(student_id):
    _load_student_or_deny(student_id, "student.update")
    v = Validator(request.form)
    v.text("full_name", "Full name", 100)
    v.date("date_of_birth", "Date of birth")
    v.text("program", "Program", 100, required=False)
    contact_fields(v)
    data = v.done()
    db.execute(
        "UPDATE students SET full_name = %s, date_of_birth = %s, program = %s, email = %s, "
        "       phone = %s, address = %s, updated_at = now(), updated_by = %s WHERE id = %s",
        (data["full_name"], data["date_of_birth"], data["program"], data["email"],
         data["phone"], data["address"], g.user.id, student_id))
    audit.log_event("STUDENT_UPDATE", audit.SUCCESS, f"student:{student_id}",
                    {"fields": sorted(data.keys())}, in_request_tx=True)
    db.commit()
    return redirect(url_for("students.view_student", student_id=student_id, notice="student_updated"))


# ---------------------------------------------------------------------------
# Record-level views (student: own, lecturer: assigned, registrar: all)
# ---------------------------------------------------------------------------

@bp.get("/me")
@require_permission("profile.read")
def my_profile():
    if g.user.student_id is None:
        abort(404)
    return redirect(url_for("students.view_student", student_id=g.user.student_id))


@bp.get("/students/<int:student_id>")
@require_permission("profile.read")
def view_student(student_id):
    student = _load_student_or_deny(student_id, "profile.read")
    can_edit_contact = can_access_student("profile.update_contact", student)
    return render_template("student_view.html", student=student,
                           can_edit_contact=can_edit_contact,
                           can_update=g.user.has("student.update"))


@bp.post("/students/<int:student_id>/contact")
@require_permission("profile.update_contact")
def update_contact(student_id):
    _load_student_or_deny(student_id, "profile.update_contact", "/contact")
    v = Validator(request.form)
    contact_fields(v)
    data = v.done()
    db.execute(
        "UPDATE students SET email = %s, phone = %s, address = %s, updated_at = now(), "
        "       updated_by = %s WHERE id = %s",
        (data["email"], data["phone"], data["address"], g.user.id, student_id))
    audit.log_event("CONTACT_UPDATE", audit.SUCCESS, f"student:{student_id}",
                    {"fields": ["email", "phone", "address"]}, in_request_tx=True)
    db.commit()
    return redirect(url_for("students.view_student", student_id=student_id, notice="contact_updated"))


@bp.get("/students/<int:student_id>/enrollments")
@require_permission("enrollment.read")
def student_enrollments(student_id):
    student = _load_student_or_deny(student_id, "enrollment.read", "/enrollments")
    rows = db.query_all(
        "SELECT e.id, c.code, c.title, c.credits, c.semester, e.status, e.enrolled_at "
        "  FROM enrollments e JOIN courses c ON c.id = e.course_id "
        " WHERE e.student_id = %s ORDER BY c.code", (student_id,))
    return render_template("student_enrollments.html", student=student, enrollments=rows)


@bp.get("/students/<int:student_id>/grades")
@require_permission("grade.read")
def student_grades(student_id):
    student = _load_student_or_deny(student_id, "grade.read", "/grades")
    scopes = g.user.scopes("grade.read")
    sees_all = "ALL" in scopes or ("OWN" in scopes and student["user_id"] == g.user.id)
    # A lecturer (ASSIGNED scope only) sees only grades of courses he/she teaches.
    rows = db.query_all(
        "SELECT c.code, c.title, c.semester, e.status, gr.score, gr.updated_at "
        "  FROM enrollments e "
        "  JOIN courses c ON c.id = e.course_id "
        "  LEFT JOIN grades gr ON gr.enrollment_id = e.id "
        " WHERE e.student_id = %s "
        "   AND (%s OR EXISTS (SELECT 1 FROM course_lecturers cl "
        "                       WHERE cl.course_id = e.course_id AND cl.lecturer_id = %s)) "
        " ORDER BY c.code", (student_id, sees_all, g.user.id))
    return render_template("student_grades.html", student=student, grades=rows)

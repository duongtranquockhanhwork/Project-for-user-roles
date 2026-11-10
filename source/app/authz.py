"""Authorization: role-based permissions with record-level scope checks.

Model
-----
* Permissions and their scope per role live in the database tables
  `role_permissions` (see database/seed-data.sql).
* A user with several roles receives the UNION of the (permission, scope)
  pairs of all roles. Conflicting role combinations are prevented when roles
  are assigned (table `role_conflicts`).
* Scopes:  OWN      - object belongs to the acting user
           ASSIGNED - object belongs to a course assigned to the acting lecturer
           ALL      - any object
* Default deny: every view must declare its access rule with one of the
  decorators below. `verify_all_endpoints_declared` stops the application at
  start-up if any endpoint has no declaration, so a forgotten check cannot
  silently expose a route.
"""
from dataclasses import dataclass, field
from functools import wraps

from flask import abort, g, request

from . import audit, db

ACCESS_ATTR = "_access_rule"


@dataclass
class CurrentUser:
    id: int
    username: str
    full_name: str
    csrf_token: str
    roles: set = field(default_factory=set)
    perms: dict = field(default_factory=dict)   # permission code -> {scopes}
    student_id: int | None = None

    def has(self, permission):
        return permission in self.perms

    def scopes(self, permission):
        return self.perms.get(permission, set())


def load_current_user(session_row):
    rows = db.query_all(
        "SELECT r.name AS role, rp.permission_code, rp.scope "
        "  FROM user_roles ur "
        "  JOIN roles r ON r.id = ur.role_id "
        "  LEFT JOIN role_permissions rp ON rp.role_id = r.id "
        " WHERE ur.user_id = %s", (session_row["user_id"],))
    user = CurrentUser(id=session_row["user_id"], username=session_row["username"],
                       full_name=session_row["full_name"],
                       csrf_token=session_row["csrf_token"])
    for row in rows:
        user.roles.add(row["role"])
        if row["permission_code"]:
            user.perms.setdefault(row["permission_code"], set()).add(row["scope"])
    student = db.query_one("SELECT id FROM students WHERE user_id = %s", (user.id,))
    user.student_id = student["id"] if student else None
    return user


# ---------------------------------------------------------------------------
# Endpoint-level decorators
# ---------------------------------------------------------------------------

def public(view):
    setattr(view, ACCESS_ATTR, "public")
    return view


def login_required(view):
    """Any authenticated user (used only for logout and the dashboard)."""
    setattr(view, ACCESS_ATTR, "login")
    return view


def require_permission(permission, deny_event="ACCESS_DENIED"):
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not g.user.has(permission):
                deny(deny_event, request.path,
                     {"required_permission": permission, "method": request.method})
            return view(*args, **kwargs)
        setattr(wrapper, ACCESS_ATTR, ("permission", permission))
        return wrapper
    return decorator


def verify_all_endpoints_declared(app):
    missing = [name for name, view in app.view_functions.items()
               if name != "static" and not hasattr(view, ACCESS_ATTR)]
    if missing:
        raise RuntimeError(f"Endpoints without an access rule (default deny): {missing}")


def access_rule(endpoint_view):
    return getattr(endpoint_view, ACCESS_ATTR, None)


def deny(event_type, target, details=None):
    """Record the rejection in the audit log and stop with HTTP 403."""
    audit.log_event(event_type, audit.DENIED, target, details)
    abort(403)


# ---------------------------------------------------------------------------
# Record-level checks
# ---------------------------------------------------------------------------

def is_assigned_lecturer(user_id, course_id):
    return db.query_one(
        "SELECT 1 FROM course_lecturers WHERE lecturer_id = %s AND course_id = %s",
        (user_id, course_id)) is not None


def lecturer_teaches_student(user_id, student_id):
    return db.query_one(
        "SELECT 1 FROM enrollments e "
        "  JOIN course_lecturers cl ON cl.course_id = e.course_id "
        " WHERE cl.lecturer_id = %s AND e.student_id = %s AND e.status = 'ENROLLED'",
        (user_id, student_id)) is not None


def can_access_student(permission, student):
    """True if the current user may apply `permission` to this student record."""
    scopes = g.user.scopes(permission)
    if "ALL" in scopes:
        return True
    if "OWN" in scopes and student["user_id"] is not None and student["user_id"] == g.user.id:
        return True
    if "ASSIGNED" in scopes and lecturer_teaches_student(g.user.id, student["id"]):
        return True
    return False


def can_access_course(permission, course_id):
    scopes = g.user.scopes(permission)
    if "ALL" in scopes:
        return True
    return "ASSIGNED" in scopes and is_assigned_lecturer(g.user.id, course_id)

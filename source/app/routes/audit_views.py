"""Read-only views for the Security Auditor."""
import re

from flask import Blueprint, render_template, request

from .. import db
from ..authz import require_permission
from ..validators import ValidationError

bp = Blueprint("audit_views", __name__, url_prefix="/audit")

_FILTER_RE = re.compile(r"^[A-Za-z0-9_().:\-]{0,64}$")


@bp.get("/logs")
@require_permission("audit.read")
def logs():
    filters = {k: (request.args.get(k) or "").strip() for k in ("event_type", "result", "actor")}
    if not all(_FILTER_RE.fullmatch(v) for v in filters.values()):
        raise ValidationError(["Invalid filter value."])
    rows = db.query_all(
        "SELECT id, ts, actor_username, event_type, target_resource, result, details, "
        "       source_ip, entry_hash "
        "  FROM audit_logs "
        " WHERE (%(event_type)s = '' OR event_type = upper(%(event_type)s)) "
        "   AND (%(result)s = '' OR result = upper(%(result)s)) "
        "   AND (%(actor)s = '' OR actor_username = %(actor)s) "
        " ORDER BY id DESC LIMIT 300", filters)
    event_types = db.query_all("SELECT DISTINCT event_type FROM audit_logs ORDER BY 1")
    return render_template("audit_logs.html", rows=rows, filters=filters,
                           event_types=[r["event_type"] for r in event_types])


@bp.get("/verify")
@require_permission("audit.read")
def verify():
    result = db.query_one("SELECT checked, first_bad_id FROM audit_verify_chain()")
    return render_template("audit_verify.html", result=result)


@bp.get("/policy")
@require_permission("policy.read")
def policy():
    perms = db.query_all(
        "SELECT p.code, p.description, r.name AS role, rp.scope "
        "  FROM permissions p "
        "  LEFT JOIN role_permissions rp ON rp.permission_code = p.code "
        "  LEFT JOIN roles r ON r.id = rp.role_id ORDER BY p.code, r.id")
    roles = [r["name"] for r in db.query_all("SELECT name FROM roles ORDER BY id")]
    matrix = {}
    descriptions = {}
    for row in perms:
        descriptions[row["code"]] = row["description"]
        cell = matrix.setdefault(row["code"], {})
        if row["role"]:
            cell[row["role"]] = row["scope"]
    conflicts = db.query_all(
        "SELECT a.name AS role_a, b.name AS role_b, rc.reason FROM role_conflicts rc "
        "  JOIN roles a ON a.id = rc.role_a JOIN roles b ON b.id = rc.role_b ORDER BY 1, 2")
    assignments = db.query_all(
        "SELECT u.username, u.is_active, string_agg(r.name, ', ' ORDER BY r.id) AS roles "
        "  FROM users u JOIN user_roles ur ON ur.user_id = u.id "
        "  JOIN roles r ON r.id = ur.role_id GROUP BY u.id ORDER BY u.username")
    return render_template("audit_policy.html", roles=roles, matrix=matrix,
                           descriptions=descriptions, conflicts=conflicts,
                           assignments=assignments)

"""User-account and role management (System Administrator).

The administrator has no academic permissions. Additional safeguards:
* an administrator cannot change his or her own roles (prevents self-escalation),
* role combinations listed in `role_conflicts` are rejected (separation of duties),
* the last active administrator cannot be removed or disabled.
"""
from flask import Blueprint, abort, current_app, g, redirect, render_template, request, url_for

from .. import audit, db, security
from ..authz import deny, require_permission
from ..validators import ROLE_NAMES, USERNAME_RE, ValidationError, Validator

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.get("/users")
@require_permission("user.read")
def list_users():
    users = db.query_all(
        "SELECT u.id, u.username, u.full_name, u.is_active, u.created_at, "
        "       (u.locked_until IS NOT NULL AND u.locked_until > now()) AS locked, "
        "       coalesce(string_agg(r.name, ', ' ORDER BY r.id), '') AS roles "
        "  FROM users u "
        "  LEFT JOIN user_roles ur ON ur.user_id = u.id "
        "  LEFT JOIN roles r ON r.id = ur.role_id "
        " GROUP BY u.id ORDER BY u.id")
    return render_template("admin_users.html", users=users, role_names=ROLE_NAMES)


@bp.post("/users")
@require_permission("user.manage")
def create_user():
    cfg = current_app.config["APP_CONFIG"]
    v = Validator(request.form)
    v.pattern("username", "Username", USERNAME_RE, transform=str.lower)
    v.text("full_name", "Full name", 100)
    v.password("password", "Initial password", cfg.MIN_PASSWORD_LENGTH)
    data = v.done()

    if db.query_one("SELECT 1 FROM users WHERE username = %s", (data["username"],)):
        raise ValidationError(["Username already exists."])
    row = db.query_one(
        "INSERT INTO users (username, password_hash, full_name, created_by) "
        "VALUES (%s, %s, %s, %s) RETURNING id",
        (data["username"], security.hash_password(data["password"]), data["full_name"],
         g.user.id))
    audit.log_event("USER_CREATE", audit.SUCCESS, f"user:{data['username']}",
                    {"user_id": row["id"]}, in_request_tx=True)
    db.commit()
    return redirect(url_for("admin.list_users", notice="user_created"))


def _load_user(user_id):
    user = db.query_one("SELECT id, username, is_active FROM users WHERE id = %s", (user_id,))
    if user is None:
        abort(404)
    return user


def _active_admin_count():
    return db.query_one(
        "SELECT count(*) AS n FROM users u JOIN user_roles ur ON ur.user_id = u.id "
        "  JOIN roles r ON r.id = ur.role_id AND r.name = 'ADMIN' WHERE u.is_active")["n"]


@bp.post("/users/<int:user_id>/status")
@require_permission("user.manage")
def change_status(user_id):
    v = Validator(request.form)
    v.choice("action", "Action", ("disable", "enable", "unlock"))
    action = v.done()["action"]
    user = _load_user(user_id)
    target = f"user:{user['username']}"

    if action == "disable":
        if user_id == g.user.id:
            deny("USER_DISABLE_DENIED", target, {"reason": "cannot_disable_self"})
        if "ADMIN" in _roles_of(user_id) and _active_admin_count() <= 1:
            deny("USER_DISABLE_DENIED", target, {"reason": "last_active_admin"})
        db.execute("UPDATE users SET is_active = false, updated_at = now() WHERE id = %s",
                   (user_id,))
        security.revoke_all_sessions(user_id)       # existing sessions end immediately
        event = "USER_DISABLE"
    elif action == "enable":
        db.execute("UPDATE users SET is_active = true, updated_at = now() WHERE id = %s",
                   (user_id,))
        event = "USER_ENABLE"
    else:
        db.execute("UPDATE users SET locked_until = NULL, failed_login_count = 0, "
                   "updated_at = now() WHERE id = %s", (user_id,))
        event = "USER_UNLOCK"
    audit.log_event(event, audit.SUCCESS, target, {"user_id": user_id}, in_request_tx=True)
    db.commit()
    return redirect(url_for("admin.list_users", notice={"USER_DISABLE": "user_disabled",
                                                        "USER_ENABLE": "user_enabled",
                                                        "USER_UNLOCK": "user_unlocked"}[event]))


def _roles_of(user_id):
    rows = db.query_all("SELECT r.name FROM user_roles ur JOIN roles r ON r.id = ur.role_id "
                        "WHERE ur.user_id = %s", (user_id,))
    return {r["name"] for r in rows}


@bp.post("/users/<int:user_id>/roles")
@require_permission("role.assign")
def change_role(user_id):
    v = Validator(request.form)
    v.choice("role", "Role", ROLE_NAMES)
    v.choice("action", "Action", ("assign", "remove"))
    data = v.done()
    user = _load_user(user_id)
    role, action = data["role"], data["action"]
    target = f"user:{user['username']}"
    event = "ROLE_ASSIGN" if action == "assign" else "ROLE_REMOVE"

    if user_id == g.user.id:
        deny(event + "_DENIED", target, {"role": role, "reason": "cannot_change_own_roles"})

    current_roles = _roles_of(user_id)
    if action == "assign":
        if role in current_roles:
            raise ValidationError([f"The user already has the {role} role."])
        conflict = db.query_one(
            "SELECT ra.name AS held, rc.reason FROM role_conflicts rc "
            "  JOIN roles ra ON ra.id IN (rc.role_a, rc.role_b) "
            "  JOIN roles rn ON rn.id IN (rc.role_a, rc.role_b) AND rn.id <> ra.id "
            " WHERE rn.name = %s AND ra.name = ANY(%s)", (role, list(current_roles)))
        if conflict:
            deny("ROLE_ASSIGN_DENIED", target,
                 {"role": role, "reason": "role_conflict", "conflicts_with": conflict["held"]})
        db.execute("INSERT INTO user_roles (user_id, role_id, assigned_by) "
                   "SELECT %s, id, %s FROM roles WHERE name = %s", (user_id, g.user.id, role))
    else:
        if role not in current_roles:
            raise ValidationError([f"The user does not have the {role} role."])
        if role == "ADMIN" and user["is_active"] and _active_admin_count() <= 1:
            deny("ROLE_REMOVE_DENIED", target, {"role": role, "reason": "last_active_admin"})
        db.execute("DELETE FROM user_roles WHERE user_id = %s "
                   "AND role_id = (SELECT id FROM roles WHERE name = %s)", (user_id, role))

    audit.log_event(event, audit.SUCCESS, target, {"role": role}, in_request_tx=True)
    db.commit()
    return redirect(url_for("admin.list_users",
                            notice="role_assigned" if action == "assign" else "role_removed"))

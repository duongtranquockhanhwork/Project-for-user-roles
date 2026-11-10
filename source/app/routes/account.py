"""Account self-service and administrator-mediated password reset.

* Every user can change their own password (current password required).
* Students and lecturers can change their display name; holders of ADMIN,
  AUDITOR or REGISTRAR cannot (deny overrides the grant of a second role).
* Forgotten password: the visitor files a request and receives a secret
  reference code. An administrator approves or rejects it. Only after approval
  can the requester, with the code, reveal a temporary password, which is
  generated at that moment, shown once, valid 24 hours and must be changed at
  the next login. Passwords are never stored in plaintext and never shown to
  administrators.
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, g, redirect, render_template, request, url_for

from .. import audit, db, security
from ..authz import deny, login_required, public, require_permission
from ..validators import EMAIL_RE, USERNAME_RE, ValidationError, Validator
from .auth import _register_failed_attempt

bp = Blueprint("account", __name__)

RENAME_DENIED_ROLES = {"ADMIN", "AUDITOR", "REGISTRAR"}
TEMP_PASSWORD_HOURS = 24
MAX_PENDING_PER_USERNAME = 3


def _hash_code(code):
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def can_rename(user):
    return user.has("account.rename") and not (user.roles & RENAME_DENIED_ROLES)


def _check_new_password(v, username, new_password, confirm, current=None):
    cfg = current_app.config["APP_CONFIG"]
    v.password("new_password", "New password", cfg.MIN_PASSWORD_LENGTH)
    if new_password != confirm:
        v.errors.append("The two new passwords do not match.")
    if username and username in new_password.lower():
        v.errors.append("The new password must not contain the username.")
    if current is not None and new_password == current:
        v.errors.append("The new password must be different from the current one.")


# ---------------------------------------------------------------------------
# My account
# ---------------------------------------------------------------------------

@bp.get("/account")
@login_required
def account():
    info = db.query_one("SELECT username, full_name, created_at, must_change_password, password_expires_at "
                        "FROM users WHERE id = %s", (g.user.id,))
    return render_template("account.html", info=info, can_rename=can_rename(g.user), errors=[])


def _account_page(errors, status=400):
    info = db.query_one("SELECT username, full_name, created_at, must_change_password, password_expires_at "
                        "FROM users WHERE id = %s", (g.user.id,))
    return render_template("account.html", info=info, can_rename=can_rename(g.user), errors=errors), status


@bp.post("/account/name")
@login_required
def change_name():
    if not can_rename(g.user):
        deny("NAME_CHANGE_DENIED", "account:name", {"roles": sorted(g.user.roles)})
    v = Validator(request.form)
    v.text("full_name", "Full name", 100, min_len=2)
    try:
        data = v.done()
    except ValidationError as exc:
        return _account_page(exc.errors)
    old = g.user.full_name
    db.execute("UPDATE users SET full_name = %s, updated_at = now() WHERE id = %s", (data["full_name"], g.user.id))
    if g.user.student_id:
        db.execute("UPDATE students SET full_name = %s, updated_at = now(), updated_by = %s WHERE id = %s",
                   (data["full_name"], g.user.id, g.user.student_id))
    audit.log_event("NAME_CHANGE", audit.SUCCESS, f"user:{g.user.username}",
                    {"old_name": old, "new_name": data["full_name"]}, in_request_tx=True)
    db.commit()
    return redirect(url_for("account.account", notice="name_changed"))


@bp.post("/account/password")
@login_required
def change_password():
    cfg = current_app.config["APP_CONFIG"]
    current = request.form.get("current_password") or ""
    new_password = request.form.get("new_password") or ""
    row = db.query_one("SELECT id, username, password_hash, failed_login_count FROM users WHERE id = %s",
                       (g.user.id,))
    if not security.verify_password(row["password_hash"], current[:128]):
        # Wrong current password counts towards the lockout, like a failed login.
        audit.log_event("PASSWORD_CHANGE_FAILURE", audit.FAILURE, f"user:{g.user.username}",
                        {"reason": "wrong_current_password"})
        _register_failed_attempt(row, cfg)
        return _account_page(["The current password is incorrect."])
    v = Validator(request.form)
    _check_new_password(v, g.user.username, new_password, request.form.get("confirm_password") or "", current)
    try:
        v.done()
    except ValidationError as exc:
        return _account_page(exc.errors)
    db.execute("UPDATE users SET password_hash = %s, must_change_password = false, password_expires_at = NULL, "
               "       failed_login_count = 0, updated_at = now() WHERE id = %s",
               (security.hash_password(new_password), g.user.id))
    # All sessions (including other devices) end; this browser gets a fresh one.
    security.revoke_all_sessions(g.user.id)
    token = security.create_session(g.user.id, cfg)
    audit.log_event("PASSWORD_CHANGE", audit.SUCCESS, f"user:{g.user.username}",
                    {"forced": bool(g.user.must_change)}, in_request_tx=True)
    db.commit()
    response = redirect(url_for("account.account", notice="password_changed"))
    security.set_session_cookie(response, token, cfg)
    return response


# ---------------------------------------------------------------------------
# Forgotten password (public)
# ---------------------------------------------------------------------------

@bp.route("/forgot-password", methods=["GET", "POST"])
@public
def forgot_password():
    if g.user:
        return redirect(url_for("account.account"))
    if request.method == "GET":
        return render_template("forgot.html", form={}, errors=[])
    form = {k: (request.form.get(k) or "").strip() for k in ("username", "email", "message")}
    try:
        v = Validator(request.form)
        v.pattern("username", "Username", USERNAME_RE, transform=str.lower)
        v.pattern("email", "Email", EMAIL_RE, required=False)
        v.text("message", "Message", 300, required=False)
        data = v.done()
    except ValidationError as exc:
        return render_template("forgot.html", form=form, errors=exc.errors), 400

    code = secrets.token_urlsafe(12)
    user = db.query_one("SELECT id FROM users WHERE username = %s", (data["username"],))
    pending = db.query_one("SELECT count(*) AS n FROM password_reset_requests "
                           "WHERE username = %s AND status = 'PENDING'", (data["username"],))["n"]
    # The response is identical whether or not the account exists (no enumeration).
    if pending < MAX_PENDING_PER_USERNAME:
        db.execute("INSERT INTO password_reset_requests (username, user_id, contact_email, message, code_hash, "
                   "source_ip) VALUES (%s, %s, %s, %s, %s, %s)",
                   (data["username"], user["id"] if user else None, data["email"], data["message"],
                    _hash_code(code), request.remote_addr))
        audit.log_event("PASSWORD_RESET_REQUEST", audit.SUCCESS, f"user:{data['username']}",
                        {"account_exists": user is not None}, actor_username="(anonymous)", in_request_tx=True)
        db.commit()
    return render_template("forgot_sent.html", code=code, username=data["username"])


def _find_request(username, code):
    if not USERNAME_RE.fullmatch(username or "") or not code or len(code) > 64:
        return None
    return db.query_one(
        "SELECT r.id, r.username, r.user_id, r.status, r.reply_message, r.created_at, r.resolved_at, "
        "       u.is_active FROM password_reset_requests r LEFT JOIN users u ON u.id = r.user_id "
        " WHERE r.username = %s AND r.code_hash = %s", (username, _hash_code(code)))


@bp.route("/forgot-password/status", methods=["GET", "POST"])
@public
def reset_status():
    if request.method == "GET":
        return render_template("reset_status.html", req=None, looked_up=False, username="", code="")
    username = (request.form.get("username") or "").strip().lower()
    code = (request.form.get("code") or "").strip()
    req = _find_request(username, code)
    return render_template("reset_status.html", req=req, looked_up=True, username=username, code=code), \
        (200 if req else 404)


@bp.post("/forgot-password/reveal")
@public
def reveal_temporary_password():
    username = (request.form.get("username") or "").strip().lower()
    code = (request.form.get("code") or "").strip()
    req = _find_request(username, code)
    if req is None or req["status"] != "APPROVED" or not req["user_id"] or not req["is_active"]:
        audit.log_event("PASSWORD_RESET_REVEAL_DENIED", audit.DENIED, f"user:{username or '(invalid)'}",
                        {"status": req["status"] if req else "not_found"}, actor_username="(anonymous)")
        return render_template("reset_status.html", req=req, looked_up=True, username=username, code=code), 403
    temp = secrets.token_urlsafe(12)            # 16 characters, ~96 bits
    expires = datetime.now(timezone.utc) + timedelta(hours=TEMP_PASSWORD_HOURS)
    db.execute("UPDATE users SET password_hash = %s, must_change_password = true, password_expires_at = %s, "
               "       failed_login_count = 0, locked_until = NULL, updated_at = now() WHERE id = %s",
               (security.hash_password(temp), expires, req["user_id"]))
    security.revoke_all_sessions(req["user_id"])
    db.execute("UPDATE password_reset_requests SET status = 'DELIVERED', delivered_at = now() WHERE id = %s",
               (req["id"],))
    audit.log_event("PASSWORD_RESET_DELIVERED", audit.SUCCESS, f"user:{username}",
                    {"request_id": req["id"], "valid_hours": TEMP_PASSWORD_HOURS},
                    actor_username="(anonymous)", in_request_tx=True)
    db.commit()
    return render_template("reset_reveal.html", username=username, temp_password=temp, expires=expires)


# ---------------------------------------------------------------------------
# Administrator: review requests
# ---------------------------------------------------------------------------

@bp.get("/admin/password-requests")
@require_permission("password_reset.manage")
def list_requests():
    rows = db.query_all(
        "SELECT r.id, r.username, r.user_id, r.contact_email, r.message, r.status, r.reply_message, "
        "       r.source_ip, r.created_at, r.resolved_at, ru.username AS resolved_by, "
        "       u.full_name, u.is_active, s.email AS email_on_file, "
        "       (SELECT string_agg(ro.name, ', ' ORDER BY ro.id) FROM user_roles ur "
        "          JOIN roles ro ON ro.id = ur.role_id WHERE ur.user_id = r.user_id) AS roles "
        "  FROM password_reset_requests r "
        "  LEFT JOIN users u ON u.id = r.user_id "
        "  LEFT JOIN students s ON s.user_id = r.user_id "
        "  LEFT JOIN users ru ON ru.id = r.resolved_by "
        " ORDER BY (r.status = 'PENDING') DESC, r.created_at DESC LIMIT 100")
    return render_template("admin_password_requests.html", rows=rows)


@bp.post("/admin/password-requests/<int:request_id>")
@require_permission("password_reset.manage")
def answer_request(request_id):
    v = Validator(request.form)
    v.choice("action", "Action", ("approve", "reject"))
    v.text("reply", "Reply", 300, required=False)
    data = v.done()
    req = db.query_one("SELECT id, username, user_id, status FROM password_reset_requests WHERE id = %s "
                       "FOR UPDATE", (request_id,))
    if req is None:
        raise ValidationError(["Unknown request."])
    if req["status"] != "PENDING":
        raise ValidationError(["This request has already been answered."])
    target = f"password_reset:{request_id}"
    if data["action"] == "approve":
        if req["user_id"] is None:
            raise ValidationError(["There is no account with this username; the request can only be rejected."])
        if req["user_id"] == g.user.id:
            deny("PASSWORD_RESET_APPROVE_DENIED", target, {"reason": "own_account"})
        status, event, notice = "APPROVED", "PASSWORD_RESET_APPROVE", "reset_approved"
    else:
        status, event, notice = "REJECTED", "PASSWORD_RESET_REJECT", "reset_rejected"
    db.execute("UPDATE password_reset_requests SET status = %s, reply_message = %s, resolved_at = now(), "
               "       resolved_by = %s WHERE id = %s", (status, data["reply"], g.user.id, request_id))
    audit.log_event(event, audit.SUCCESS, target, {"username": req["username"]}, in_request_tx=True)
    db.commit()
    return redirect(url_for("account.list_requests", notice=notice))

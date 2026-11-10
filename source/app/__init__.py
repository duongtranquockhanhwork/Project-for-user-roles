"""University Records System - application factory."""
import logging
import secrets

import psycopg2
from flask import Flask, abort, g, redirect, render_template, request, url_for
from werkzeug.exceptions import HTTPException

from . import audit, authz, db, security, ui
from .config import Config
from .validators import ValidationError

ERROR_MESSAGES = {
    400: "The request was invalid.",
    401: "You are not logged in or your session has expired.",
    403: "You are not authorized to perform this action.",
    404: "The requested resource was not found.",
    405: "This method is not allowed.",
    413: "The request is too large.",
    500: "An internal error occurred. Please try again later.",
}


NOTICES = {
    "grade_saved": "Grade saved.",
    "contact_updated": "Your contact information has been updated.",
    "student_created": "Student record created.",
    "student_updated": "Student record updated.",
    "enrollment_created": "Enrollment created.",
    "enrollment_dropped": "Enrollment dropped.",
    "user_created": "User account created.",
    "user_disabled": "User account disabled. Its sessions were revoked.",
    "user_enabled": "User account enabled.",
    "user_unlocked": "User account unlocked.",
    "role_assigned": "Role assigned.",
    "role_removed": "Role removed.",
    "account_created": "Your student account has been created. You can sign in now.",
    "course_created": "Class created.",
    "lecturer_assigned": "Lecturer assigned to the class.",
    "lecturer_removed": "Lecturer removed from the class.",
    "class_joined": "You have joined the class.",
    "class_left": "You have left the class.",
    "teaching_started": "You are now the lecturer of this class.",
    "password_changed": "Your password has been changed. Other sessions were signed out.",
    "name_changed": "Your name has been updated.",
    "password_change_required": "Please choose a new password to continue.",
    "reset_approved": "Request approved. The user can now reveal a one-time temporary password.",
    "reset_rejected": "Request rejected.",
}

# Endpoints that stay reachable while a temporary password must be changed.
FORCED_CHANGE_ALLOWED = {"account.account", "account.change_password", "auth.logout"}


def create_app():
    app = Flask(__name__)
    cfg = Config()
    app.config["APP_CONFIG"] = cfg
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024
    app.config["PROPAGATE_EXCEPTIONS"] = False
    app.config["TRAP_HTTP_EXCEPTIONS"] = False
    app.debug = False                       # never expose the debugger
    logging.basicConfig(level=logging.INFO)

    db.init_app(app)
    ui.init_app(app)

    from .routes import account, admin, audit_views, auth, courses, enrollments, students
    for module in (auth, account, students, courses, enrollments, admin, audit_views):
        app.register_blueprint(module.bp)

    authz.verify_all_endpoints_declared(app)

    # ------------------------------------------------------------------
    # Authentication, default deny and CSRF - runs before every request
    # ------------------------------------------------------------------
    @app.before_request
    def authenticate_and_authorize():
        g.user = None
        g.session_token = None
        if request.endpoint is None or request.endpoint == "static":
            return None  # unknown URL -> 404; static files are public

        token = request.cookies.get(cfg.SESSION_COOKIE)
        session_row = security.load_session(token, cfg) if token else None
        if session_row:
            g.user = authz.load_current_user(session_row)
            g.session_token = token

        rule = authz.access_rule(app.view_functions[request.endpoint])
        if rule is None:
            abort(403)                       # default deny (defensive)
        if rule == "public":
            return None
        if g.user is None:
            abort(401)
        if g.user.must_change and request.endpoint not in FORCED_CHANGE_ALLOWED:
            return redirect(url_for("account.account", notice="password_change_required"))

        if request.method not in ("GET", "HEAD", "OPTIONS"):
            supplied = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
            if not security.csrf_valid(g.user.csrf_token, supplied):
                authz.deny("CSRF_REJECTED", request.path, {"method": request.method})
        return None

    @app.after_request
    def add_headers(response):
        return security.apply_security_headers(response)

    @app.context_processor
    def inject_user():
        user = g.get("user")
        # Only fixed, server-defined messages can be shown (no reflected text).
        notice = NOTICES.get(request.args.get("notice", ""))
        pending = 0
        if user is not None and user.has("password_reset.manage"):
            pending = db.query_one("SELECT count(*) AS n FROM password_reset_requests "
                                   "WHERE status = 'PENDING'")["n"]
        return {"current_user": user, "csrf_token": user.csrf_token if user else "",
                "notice": notice, "pending_resets": pending}

    # ------------------------------------------------------------------
    # Error handling: generic pages, no stack traces / SQL / configuration
    # ------------------------------------------------------------------
    def render_error(code, errors=None):
        return render_template("error.html", code=code,
                               message=ERROR_MESSAGES.get(code, ERROR_MESSAGES[500]),
                               errors=errors or []), code

    @app.errorhandler(ValidationError)
    def handle_validation(exc):
        db.rollback()
        return render_error(400, exc.errors)

    @app.errorhandler(HTTPException)
    def handle_http(exc):
        return render_error(exc.code if exc.code in ERROR_MESSAGES else 400)

    @app.errorhandler(psycopg2.Error)
    def handle_db_error(exc):
        try:
            db.rollback()
        except psycopg2.Error:
            pass
        if getattr(exc, "pgcode", None) == "42501":
            # Rejected by a database guard (trigger or privilege): defence in depth.
            audit.log_event("DB_GUARD_DENIED", audit.DENIED, request.path,
                            {"method": request.method})
            return render_error(403)
        if getattr(exc, "pgcode", None) in ("23505", "23514"):
            # Unique / check constraint (e.g. class full, second lecturer): reject without detail.
            return render_error(400, ["The request conflicts with a data constraint "
                                      "(for example, the class is full or already has a lecturer)."])
        incident = secrets.token_hex(4)
        app.logger.error("Database error (incident %s): %s", incident, type(exc).__name__)
        return render_error(500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        incident = secrets.token_hex(4)
        app.logger.exception("Unhandled error (incident %s)", incident)
        return render_error(500)

    return app

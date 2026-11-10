"""Login, logout, self-registration and dashboard."""
from datetime import date

from flask import Blueprint, current_app, g, redirect, render_template, request, url_for

from .. import audit, db, security
from ..authz import login_required, public
from ..validators import EMAIL_RE, USERNAME_RE, ValidationError, Validator

bp = Blueprint("auth", __name__)

# One message for every failure reason, so the response never reveals whether
# the username exists, the account is disabled or the account is locked.
GENERIC_LOGIN_ERROR = "Invalid username or password."


@bp.get("/healthz")
@public
def healthz():
    return {"status": "ok"}


@bp.route("/login", methods=["GET", "POST"])
@public
def login():
    cfg = current_app.config["APP_CONFIG"]
    if request.method == "GET":
        if g.user:
            return redirect(url_for("auth.dashboard"))
        return render_template("login.html", logged_out="logged_out" in request.args)

    username = (request.form.get("username") or "").strip().lower()
    password = request.form.get("password") or ""
    valid_format = bool(USERNAME_RE.fullmatch(username)) and 0 < len(password) <= 128

    user = None
    if valid_format:
        user = db.query_one(
            "SELECT id, username, password_hash, is_active, failed_login_count, must_change_password, "
            "       (locked_until IS NOT NULL AND locked_until > now()) AS locked, "
            "       (password_expires_at IS NOT NULL AND password_expires_at < now()) AS expired "
            "  FROM users WHERE username = %s", (username,))

    if user is None:
        security.burn_verification_time(password[:128])
        reason = "unknown_user" if valid_format else "invalid_input_format"
    elif user["locked"]:
        security.burn_verification_time(password)
        reason = "account_locked"
    elif not security.verify_password(user["password_hash"], password):
        reason = "wrong_password"
        _register_failed_attempt(user, cfg)
    elif not user["is_active"]:
        reason = "account_disabled"
    elif user["expired"]:
        reason = "temporary_password_expired"
    else:
        reason = None

    if reason:
        audit.log_event(
            "LOGIN_FAILURE", audit.FAILURE,
            f"user:{username}" if USERNAME_RE.fullmatch(username) else "user:(invalid format)",
            {"reason": reason},
            actor_id=user["id"] if user else None,
            actor_username="(anonymous)")
        return render_template("login.html", error=GENERIC_LOGIN_ERROR), 401

    # Successful login: reset counters, upgrade hash if parameters changed,
    # discard any pre-existing session (anti-fixation) and issue a new one.
    db.execute("UPDATE users SET failed_login_count = 0, locked_until = NULL WHERE id = %s",
               (user["id"],))
    if security.needs_rehash(user["password_hash"]):
        db.execute("UPDATE users SET password_hash = %s, updated_at = now() WHERE id = %s",
                   (security.hash_password(password), user["id"]))
    security.revoke_session(request.cookies.get(cfg.SESSION_COOKIE))
    token = security.create_session(user["id"], cfg)
    audit.log_event("LOGIN_SUCCESS", audit.SUCCESS, f"user:{user['username']}",
                    actor_id=user["id"], actor_username=user["username"], in_request_tx=True)
    db.commit()

    response = redirect(url_for("account.account", notice="password_change_required")
                        if user["must_change_password"] else url_for("auth.dashboard"))
    security.set_session_cookie(response, token, cfg)
    return response


def _register_failed_attempt(user, cfg):
    row = db.query_one(
        "UPDATE users SET failed_login_count = failed_login_count + 1 "
        " WHERE id = %s RETURNING failed_login_count", (user["id"],))
    if row["failed_login_count"] >= cfg.LOCKOUT_THRESHOLD:
        db.execute(
            "UPDATE users SET failed_login_count = 0, "
            "       locked_until = now() + make_interval(mins => %s), updated_at = now() "
            " WHERE id = %s", (cfg.LOCKOUT_MINUTES, user["id"]))
        audit.log_event("ACCOUNT_LOCKED", audit.SUCCESS, f"user:{user['username']}",
                        {"failed_attempts": cfg.LOCKOUT_THRESHOLD,
                         "lock_minutes": cfg.LOCKOUT_MINUTES},
                        actor_id=None, actor_username="(system)", in_request_tx=True)
    db.commit()


@bp.route("/register", methods=["GET", "POST"])
@public
def register():
    """Self-service sign-up for students.

    * The new account always receives exactly one role: STUDENT. Any role or
      permission field sent by the client is ignored.
    * A NEW student profile with a generated student code is created and
      linked to the account. Self-registration can never claim an existing
      student record (that would let anyone read another student's grades);
      linking an existing record remains a registrar task.
    """
    cfg = current_app.config["APP_CONFIG"]
    if g.user:
        return redirect(url_for("auth.dashboard"))
    if request.method == "GET":
        return render_template("register.html", form={}, errors=[])

    form = {k: (request.form.get(k) or "").strip() for k in ("full_name", "username", "email")}
    try:
        v = Validator(request.form)
        v.text("full_name", "Full name", 100, min_len=2)
        v.pattern("username", "Username", USERNAME_RE, transform=str.lower)
        v.pattern("email", "Email", EMAIL_RE)
        v.password("password", "Password", cfg.MIN_PASSWORD_LENGTH)
        # Collect every problem so that the visitor sees all messages at once.
        password = request.form.get("password") or ""
        username = (v.data.get("username") or "").lower()
        if password != (request.form.get("confirm_password") or ""):
            v.errors.append("The two passwords do not match.")
        if username and username in password.lower():
            v.errors.append("The password must not contain the username.")
        if username and USERNAME_RE.fullmatch(username) and db.query_one(
                "SELECT 1 FROM users WHERE username = %s", (username,)):
            v.errors.append("This username is already taken.")
        data = v.done()
    except ValidationError as exc:
        return render_template("register.html", form=form, errors=exc.errors), 400

    user = db.query_one(
        "INSERT INTO users (username, password_hash, full_name) VALUES (%s, %s, %s) RETURNING id",
        (data["username"], security.hash_password(data["password"]), data["full_name"]))
    db.execute("INSERT INTO user_roles (user_id, role_id) SELECT %s, id FROM roles WHERE name = 'STUDENT'",
               (user["id"],))
    student_id = db.query_one("SELECT nextval('students_id_seq') AS id")["id"]
    student_code = f"S{date.today().year}{student_id:03d}"
    db.execute("INSERT INTO students (id, user_id, student_code, full_name, email, created_by, updated_by) "
               "VALUES (%s, %s, %s, %s, %s, %s, %s)",
               (student_id, user["id"], student_code, data["full_name"], data["email"],
                user["id"], user["id"]))
    audit.log_event("USER_REGISTER", audit.SUCCESS, f"user:{data['username']}",
                    {"role": "STUDENT", "student_code": student_code},
                    actor_id=user["id"], actor_username=data["username"], in_request_tx=True)
    db.commit()
    return redirect(url_for("auth.login", notice="account_created"))


@bp.post("/logout")
@login_required
def logout():
    cfg = current_app.config["APP_CONFIG"]
    security.revoke_session(g.session_token)
    audit.log_event("LOGOUT", audit.SUCCESS, f"user:{g.user.username}", in_request_tx=True)
    db.commit()
    response = redirect(url_for("auth.login", logged_out=1))
    security.clear_session_cookie(response, cfg)
    return response


@bp.get("/")
@login_required
def dashboard():
    """Role-aware overview. Each block is computed only from data the user's
    permissions already allow, so the dashboard never widens access."""
    user = g.user
    stats = {}
    if user.student_id and "OWN" in user.scopes("grade.read"):
        stats["student"] = db.query_one(
            "SELECT count(*) FILTER (WHERE e.status = 'ENROLLED') AS courses, "
            "       coalesce(sum(c.credits) FILTER (WHERE e.status = 'ENROLLED'), 0) AS credits, "
            "       count(gr.score) AS graded, "
            "       round(sum(gr.score * c.credits) / nullif(sum(c.credits) FILTER (WHERE gr.score IS NOT NULL), 0), 2) AS average "
            "  FROM enrollments e JOIN courses c ON c.id = e.course_id "
            "  LEFT JOIN grades gr ON gr.enrollment_id = e.id WHERE e.student_id = %s",
            (user.student_id,))
    if "ASSIGNED" in user.scopes("course.read"):
        stats["lecturer"] = db.query_one(
            "SELECT count(DISTINCT cl.course_id) AS courses, "
            "       count(e.id) FILTER (WHERE e.status = 'ENROLLED') AS students, "
            "       count(e.id) FILTER (WHERE e.status = 'ENROLLED' AND gr.score IS NULL) AS pending "
            "  FROM course_lecturers cl "
            "  LEFT JOIN enrollments e ON e.course_id = cl.course_id "
            "  LEFT JOIN grades gr ON gr.enrollment_id = e.id WHERE cl.lecturer_id = %s", (user.id,))
    if user.has("student.search"):
        stats["registrar"] = db.query_one(
            "SELECT (SELECT count(*) FROM students) AS students, "
            "       (SELECT count(*) FROM enrollments WHERE status = 'ENROLLED') AS enrollments, "
            "       (SELECT count(*) FROM courses) AS courses")
    if user.has("audit.read"):
        stats["auditor"] = db.query_one(
            "SELECT count(*) AS entries, "
            "       count(*) FILTER (WHERE result = 'DENIED' AND ts > now() - interval '24 hours') AS denied, "
            "       count(*) FILTER (WHERE event_type = 'LOGIN_FAILURE' "
            "                        AND ts > now() - interval '24 hours') AS failed_logins "
            "  FROM audit_logs")
    if user.has("user.read"):
        stats["admin"] = db.query_one(
            "SELECT count(*) AS users, count(*) FILTER (WHERE is_active) AS active, "
            "       count(*) FILTER (WHERE NOT is_active) AS disabled, "
            "       count(*) FILTER (WHERE locked_until > now()) AS locked FROM users")
    return render_template("dashboard.html", stats=stats)

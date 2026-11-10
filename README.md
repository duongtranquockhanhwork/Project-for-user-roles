# Source code: University Records System

This is the technical documentation of the source code. For running the system and the grading accounts, see the
[main README](../README.md).

## 1. Technology stack

| Layer | Technology |
|---|---|
| Web application | Python 3.11, Flask 3.1, Jinja2 templates, served by gunicorn 23 |
| User interface | Custom CSS design system (`static/style.css`), inline SVG icons, small progressive-enhancement script (`static/app.js`) |
| Password hashing | Argon2id via `argon2-cffi` (memory 64 MiB, 3 iterations, 4 lanes) |
| Database | PostgreSQL 16 (psycopg2, parameterized queries only) |
| Runtime | Docker Compose: container `db` (postgres:16-alpine) and container `app` (python:3.11-slim, non-root user) |
| Tests | pytest + requests (HTTP black-box), psycopg2 (database inspection), Playwright with Edge (screenshots) |

## 2. Folder layout

```
src_code/
├── docker-compose.yml          db + app services; ports bound to 127.0.0.1 only
├── .env.example                secrets template (copy to .env; .env is git-ignored)
├── source/                     web application (built into the "app" image)
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── wsgi.py                 gunicorn entry point
│   ├── scripts/hash_password.py   prints an Argon2id hash (for preparing seed data)
│   └── app/
│       ├── __init__.py         application factory, request pipeline, CSRF, error handlers
│       ├── config.py           configuration from environment variables
│       ├── db.py               connection pool and query helpers (bound parameters only)
│       ├── security.py         password hashing, server-side sessions, CSRF, HTTP headers
│       ├── authz.py            default deny, permission decorators, record-level scope checks
│       ├── audit.py            audit logging with secret stripping
│       ├── validators.py       server-side allow-list input validation
│       ├── ui.py               template helpers: SVG icon set, initials, grade bands
│       ├── routes/
│       │   ├── auth.py         login, logout, dashboard, lockout
│       │   ├── students.py     profiles, contact update, enrollments and grades of a student
│       │   ├── courses.py      course list, roster, grade entry
│       │   ├── enrollments.py  enrollment management (registrar)
│       │   ├── admin.py        users and role assignment (administrator)
│       │   └── audit_views.py  audit log, integrity check, access-control configuration (auditor)
│       ├── templates/          Jinja2 templates + _macros.html (auto-escaped, no inline script or style)
│       └── static/             style.css, app.js, favicon.svg
├── database/
│   ├── init/00-create-roles.sh creates the application role uni_app from APP_DB_PASSWORD
│   ├── schema.sql              tables, constraints, triggers, grants
│   └── seed-data.sql           roles, permissions, role conflicts, demo data
├── tests/
│   ├── conftest.py             HTTP client, DB fixtures, result and evidence recording
│   ├── test_1_authentication.py   T01–T05, T21–T25
│   ├── test_2_authorization.py    T06–T17, T26–T34
│   ├── test_3_injection.py        T18–T19, T35–T38
│   ├── test_4_audit.py            T20, T39–T42
│   ├── test_5_database.py         T43–T44
│   ├── capture_screenshots.py  35 evidence screenshots + index.json (section, caption, test id)
│   └── requirements.txt
├── evidence/                   generated: test-results.html/.md, http/Txx.txt, screenshots/ (+ index.json)
├── contribution/               member-a/b/c.md and .pdf (individual statements)
└── docs/
    ├── dfd.svg                 system and data-flow diagram
    ├── group.json              group information used in the report
    ├── build_report.py         builds ../report/report.docx and report.pdf from the faculty template
    ├── build_contributions.py  converts contribution/*.md to PDF
    └── demo-script.md          storyboard of the demonstration video
```

## 3. Request pipeline

Every request goes through these steps:

1. **Session.** `authenticate_and_authorize()` in `app/__init__.py` reads the `urs_session` cookie. It looks up
   the SHA-256 hash of the token in the `sessions` table and checks revocation, the 8-hour absolute expiry, the
   30-minute idle timeout and whether the account is still active.
2. **Default deny.** Every route must declare an access rule with `@public`, `@login_required` or
   `@require_permission("...")`. `authz.verify_all_endpoints_declared()` raises an error at start-up if any route
   is missing one. A request without a session gets 401, and a request without the required permission gets 403
   and an audit entry.
3. **CSRF.** Every POST from a logged-in user must carry the session's `csrf_token`, compared in constant time.
4. **Validation and record-level checks.** Handlers validate input with `validators.Validator` and call
   `can_access_student()` or `can_access_course()` before reading or changing a specific record.
5. **Data access.** Each request runs in one transaction, and every SQL statement uses `%s` bound parameters.
6. **Response.** Templates are auto-escaped. `security.apply_security_headers()` adds the CSP
   (`script-src 'self'`), `X-Frame-Options: DENY`, `nosniff`, `no-referrer` and `Cache-Control: no-store`.

## 4. User interface

* **Layout:** a role-aware sidebar (only sections the user's permissions allow), a top bar with breadcrumb, user
  chip and logout, page headers, summary tiles and cards. Each role has its own dashboard with figures computed
  only from data that the role may already see (`routes/auth.py::dashboard`).
* **Feedback:** after an action the handler redirects with `?notice=<code>`. The text comes from the fixed
  dictionary `NOTICES` in `app/__init__.py`, so no request data is reflected, and it is shown as an auto-hiding
  toast.
* **Motion and usability (`static/app.js`):** page transitions, entrance animations, count-up statistics, loading
  state on buttons, confirmation dialogs (`data-confirm`) before Drop and Disable, a password reveal button and
  a mobile slide-in menu. Everything is disabled under `prefers-reduced-motion`. The script contains no
  security logic.
* **CSP compatibility:** there are no inline scripts and no `style=""` attributes; icons are inline SVG, so the policy
  `script-src 'self'; style-src 'self'` stays strict.

## 5. Authorization model

Permissions and their scopes are data in the database (`role_permissions`, see `database/seed-data.sql`):

| Scope | Meaning | Check |
|---|---|---|
| `OWN` | the record belongs to the acting user | `students.user_id = current user` |
| `ASSIGNED` | the record belongs to a course assigned to the lecturer | row in `course_lecturers` |
| `ALL` | any record | none |

* **Multiple roles:** a user receives the union of the (permission, scope) pairs of all of their roles.
* **Grades** (`routes/courses.py`): only `grade.write` with scope ASSIGNED, never for the lecturer's own
  enrollment, and only for active enrollments. The course is taken from the enrollment in the database. The trigger
  `grades_write_guard` re-checks these rules.
* **Roles** (`routes/admin.py`): administrators cannot change their own roles or disable themselves; pairs in
  `role_conflicts` (ADMIN+AUDITOR, LECTURER+REGISTRAR, STUDENT+REGISTRAR) are rejected, also by the trigger
  `user_roles_conflict_guard`; the last active administrator cannot be removed.
* **IDOR:** a user without the ALL scope gets the same 403 for a foreign record and for a non-existent id.

## 6. Database security (`database/schema.sql`)

* `uni_dba` (superuser) is used only for container initialization. The application connects as `uni_app`, which
  has no superuser, CREATEROLE, CREATEDB or BYPASSRLS attribute and owns no table.
* Grants are table- and column-level. There is no DELETE on users, students, enrollments or grades. The policy
  tables, courses and lecturer assignments are SELECT-only. `audit_logs` allows only INSERT and SELECT.
* `users.password_hash` has a CHECK constraint that accepts only `$argon2id$...` values.
* **Audit log.** The trigger `audit_logs_before_insert` assigns the id, a server timestamp, `prev_hash` and
  `entry_hash` (SHA-256 chain). The triggers `audit_logs_no_update` and `audit_logs_no_truncate` block UPDATE,
  DELETE and TRUNCATE for everyone. `audit_verify_chain()` recomputes the chain.

## 7. Audit events

| Event | Result |
|---|---|
| LOGIN_SUCCESS / LOGIN_FAILURE / LOGOUT / ACCOUNT_LOCKED | SUCCESS / FAILURE |
| USER_CREATE / USER_DISABLE / USER_ENABLE / USER_UNLOCK | SUCCESS |
| ROLE_ASSIGN / ROLE_REMOVE (and `_DENIED` variants) | SUCCESS / DENIED |
| GRADE_CREATE / GRADE_UPDATE (old and new score) | SUCCESS |
| GRADE_MODIFY_DENIED, RECORD_ACCESS_DENIED, ACCESS_DENIED, CSRF_REJECTED, DB_GUARD_DENIED | DENIED |
| STUDENT_CREATE / STUDENT_UPDATE / CONTACT_UPDATE / ENROLLMENT_CREATE / ENROLLMENT_DROP | SUCCESS |

Each entry stores the timestamp, actor id and username, event type, target resource, result, JSON details and
source IP. `audit.py` removes keys such as `password`, `token` and `csrf_token`. Successful changes are logged in
the same transaction as the change; rejections are logged in a separate transaction.

## 8. Configuration

| Variable | Used by | Description |
|---|---|---|
| `DBA_USER`, `DBA_PASSWORD` | db container | PostgreSQL superuser for initialization only |
| `APP_DB_PASSWORD` | db init script, app | Password of the least-privilege role `uni_app` |
| `COOKIE_SECURE` | app | `true` when served over HTTPS: adds `Secure` and the `__Host-` cookie prefix |

The app container also receives `DB_HOST`, `DB_PORT`, `DB_NAME` and `DB_USER` from `docker-compose.yml`. Session
lifetime, lockout threshold (5 attempts, 15 minutes) and minimum password length (12) are set in `app/config.py`.

## 9. Common commands

Run all commands from the `src_code` folder.

Start or rebuild the containers:

```bash
docker compose up -d --build
```

Follow the application log:

```bash
docker compose logs -f app
```

Open a database shell as the DBA (the password is not needed inside the container):

```bash
docker compose exec db psql -U uni_dba -d uni_records
```

Reset the database to the seed data:

```bash
docker compose down -v
```

Run the test suite (the system must be running):

```bash
python -m pytest tests
```

Capture the evidence screenshots:

```bash
python tests/capture_screenshots.py
```

Rebuild the report (Windows with Microsoft Word; run the tests and screenshots first):

```bash
python docs/build_report.py
```

Convert the contribution statements to PDF:

```bash
python docs/build_contributions.py
```

## 10. Demo data

`database/seed-data.sql` creates 11 accounts (password `<username>@Demo2026`), 3 courses, 6 student profiles,
9 enrollments and 6 grades. The account list is in the [main README](../README.md#3-accounts-for-grading).
To prepare a hash for a new seed account, run `python source/scripts/hash_password.py`; the password is read
without being echoed.

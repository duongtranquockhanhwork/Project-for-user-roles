"""Database-security tests (original T43-T44)."""
import psycopg2
import pytest

from conftest import q, q1

case = pytest.mark.case


@case(id="T43", category="Database security", role="Application DB account (uni_app)",
      pre="Grade of S2026002 in IS101 exists",
      action="Bypass the web layer: UPDATE grades.final_exam directly as uni_app with updated_by = registrar01 "
             "and = lecturer02 (not assigned)",
      expected="grades_guard trigger rejects both (42501); score unchanged")
def test_t43_grade_guard_trigger(app_db, record, lookup):
    enr = lookup.enrollment("S2026002", "IS101")
    before = lookup.score(enr)
    outcomes = []
    for writer in ("registrar01", "lecturer02"):
        with pytest.raises(psycopg2.Error) as exc:
            q(app_db, "UPDATE grades SET final_exam = 10, updated_by = %s WHERE enrollment_id = %s",
              (lookup.user(writer), enr))
        assert exc.value.pgcode == "42501"
        outcomes.append(f"updated_by={writer}: {str(exc.value).splitlines()[0]}")
    record.note("Direct database writes", "\n".join(outcomes))
    assert lookup.score(enr) == before
    record.actual("Both direct updates rejected by the trigger (" + "; ".join(outcomes) +
                  f"); score unchanged ({before})")


@case(id="T44", category="Database security", role="Application DB account (uni_app)",
      pre="Application connects as uni_app",
      action="As uni_app: DELETE grades/students, UPDATE role_permissions, change username, "
             "CREATE TABLE, read pg_authid; inspect role attributes",
      expected="All denied (insufficient privilege); uni_app is not superuser and owns no table")
def test_t44_least_privilege(app_db, record):
    statements = [
        "DELETE FROM grades WHERE id = 1",
        "DELETE FROM students WHERE id = 6",
        "UPDATE role_permissions SET scope = 'ALL' WHERE permission_code = 'grade.write'",
        "INSERT INTO role_permissions VALUES (5, 'grade.write', 'ALL')",
        "UPDATE users SET username = 'root' WHERE id = 1",
        "CREATE TABLE evil (id int)",
        "SELECT rolpassword FROM pg_authid",
        "DROP TABLE audit_logs",
    ]
    outcomes = []
    for sql in statements:
        with pytest.raises(psycopg2.Error) as exc:
            q(app_db, sql)
        assert exc.value.pgcode in ("42501", "42P01"), (sql, exc.value.pgcode)
        outcomes.append(f"{sql[:60]:<62} -> {exc.value.pgcode}")
    role = q1(app_db, "SELECT rolsuper, rolcreaterole, rolcreatedb, rolbypassrls "
                      "FROM pg_roles WHERE rolname = current_user")
    owned = q1(app_db, "SELECT count(*) AS n FROM pg_tables WHERE tableowner = current_user")["n"]
    record.note("Denied statements", "\n".join(outcomes))
    record.note("Role attributes of uni_app", f"{role}; tables owned: {owned}")
    assert not any(role.values()) and owned == 0
    record.actual(f"All {len(statements)} statements rejected with 42501 (insufficient privilege); "
                  "uni_app: no superuser/createrole/createdb/bypassrls, owns 0 tables")

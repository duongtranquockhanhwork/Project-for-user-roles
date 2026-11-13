-- =============================================================================
-- University Records System - database schema (PostgreSQL 16)
--
-- Run as the database owner (the DBA account used during container init).
-- The low-privilege application role `uni_app` must already exist; it is
-- created by database/init/00-create-roles.sql so that its password comes from
-- the environment and is never committed to the repository.
--
-- Security features implemented at the database layer:
--   * password_hash column only accepts Argon2id hashes (no plaintext possible)
--   * role-conflict (separation of duties) trigger on user_roles
--   * grade-write guard trigger (defence in depth for course-assignment rule)
--   * class limits: one lecturer (UNIQUE) and at most 30 students (capacity trigger)
--   * course total computed by the database from four weighted grade components
--   * append-only, hash-chained audit_logs table
--   * least-privilege grants for the application role (table + column level)
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- 1. Roles, permissions and the access-control configuration
-- -----------------------------------------------------------------------------
CREATE TABLE roles (
    id          smallint    PRIMARY KEY,
    name        varchar(20) NOT NULL UNIQUE
                CHECK (name IN ('STUDENT', 'LECTURER', 'REGISTRAR', 'AUDITOR', 'ADMIN')),
    description text        NOT NULL
);

CREATE TABLE permissions (
    code        varchar(40) PRIMARY KEY,
    description text        NOT NULL
);

-- scope: OWN      = only objects owned by the acting user
--        ASSIGNED = only objects belonging to courses assigned to the lecturer
--        ALL      = every object of that type
CREATE TABLE role_permissions (
    role_id         smallint    NOT NULL REFERENCES roles (id),
    permission_code varchar(40) NOT NULL REFERENCES permissions (code),
    scope           varchar(10) NOT NULL CHECK (scope IN ('OWN', 'ASSIGNED', 'ALL')),
    PRIMARY KEY (role_id, permission_code, scope)
);

-- Pairs of roles that must never be held by the same user (separation of duties).
CREATE TABLE role_conflicts (
    role_a smallint NOT NULL REFERENCES roles (id),
    role_b smallint NOT NULL REFERENCES roles (id),
    reason text     NOT NULL,
    PRIMARY KEY (role_a, role_b),
    CHECK (role_a < role_b)
);

-- -----------------------------------------------------------------------------
-- 2. User accounts and sessions
-- -----------------------------------------------------------------------------
CREATE TABLE users (
    id                 serial       PRIMARY KEY,
    username           varchar(32)  NOT NULL UNIQUE CHECK (username ~ '^[a-z0-9_.]{3,32}$'),
    -- Only Argon2id encoded hashes are accepted: plaintext cannot be stored.
    password_hash      text         NOT NULL CHECK (password_hash LIKE '$argon2id$%'),
    full_name          varchar(100) NOT NULL,
    is_active          boolean      NOT NULL DEFAULT true,
    failed_login_count integer      NOT NULL DEFAULT 0 CHECK (failed_login_count >= 0),
    locked_until       timestamptz,
    -- Set after an administrator-approved password reset: the temporary
    -- password must be changed at the next login and expires at password_expires_at.
    must_change_password boolean    NOT NULL DEFAULT false,
    password_expires_at  timestamptz,
    created_at         timestamptz  NOT NULL DEFAULT now(),
    created_by         integer      REFERENCES users (id),
    updated_at         timestamptz  NOT NULL DEFAULT now()
);

CREATE TABLE user_roles (
    user_id     integer     NOT NULL REFERENCES users (id),
    role_id     smallint    NOT NULL REFERENCES roles (id),
    assigned_by integer     REFERENCES users (id),
    assigned_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, role_id)
);

-- "Forgot password" requests, answered by an administrator.
-- No password is ever stored here. The requester receives a random reference
-- code (only its SHA-256 hash is stored). After approval the temporary password
-- is generated at the moment the requester reveals it and is shown only once.
CREATE TABLE password_reset_requests (
    id            serial       PRIMARY KEY,
    username      varchar(32)  NOT NULL,                 -- as typed (valid format only)
    user_id       integer      REFERENCES users (id),    -- NULL if no such account
    contact_email varchar(254),
    message       varchar(300),
    code_hash     char(64)     NOT NULL UNIQUE,
    status        varchar(10)  NOT NULL DEFAULT 'PENDING'
                  CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED', 'DELIVERED')),
    reply_message varchar(300),
    source_ip     varchar(45),
    created_at    timestamptz  NOT NULL DEFAULT now(),
    resolved_at   timestamptz,
    resolved_by   integer      REFERENCES users (id),
    delivered_at  timestamptz
);
CREATE INDEX password_reset_requests_status_idx ON password_reset_requests (status);

-- Server-side sessions. Only the SHA-256 hash of the session token is stored,
-- so a database leak does not reveal usable session cookies.
CREATE TABLE sessions (
    token_hash   char(64)    PRIMARY KEY,
    user_id      integer     NOT NULL REFERENCES users (id),
    csrf_token   varchar(64) NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    expires_at   timestamptz NOT NULL,
    revoked_at   timestamptz
);
CREATE INDEX sessions_user_idx ON sessions (user_id);

-- -----------------------------------------------------------------------------
-- 3. Academic data
-- -----------------------------------------------------------------------------
CREATE TABLE students (
    id            serial       PRIMARY KEY,
    user_id       integer      UNIQUE REFERENCES users (id),
    student_code  varchar(12)  NOT NULL UNIQUE CHECK (student_code ~ '^[A-Z0-9]{5,12}$'),
    full_name     varchar(100) NOT NULL,
    date_of_birth date,
    program       varchar(100),
    email         varchar(254),
    phone         varchar(20),
    address       varchar(200),
    created_at    timestamptz  NOT NULL DEFAULT now(),
    created_by    integer      REFERENCES users (id),
    updated_at    timestamptz  NOT NULL DEFAULT now(),
    updated_by    integer      REFERENCES users (id)
);

CREATE TABLE courses (
    id       serial       PRIMARY KEY,
    code     varchar(10)  NOT NULL UNIQUE CHECK (code ~ '^[A-Z]{2,4}[0-9]{3,4}$'),
    title    varchar(120) NOT NULL,
    credits  smallint     NOT NULL CHECK (credits BETWEEN 1 AND 10),
    semester varchar(10)  NOT NULL CHECK (semester ~ '^[0-9]{4}-[1-3]$'),
    -- Each class holds at most 30 students (enforced by enrollments_capacity_guard).
    capacity smallint     NOT NULL DEFAULT 30 CHECK (capacity BETWEEN 1 AND 30),
    -- Enrollment lock: a locked class accepts no self-enrollment by students.
    is_locked  boolean     NOT NULL DEFAULT false,
    -- Set when the lecturer (or registrar) starts teaching; the class is locked
    -- at that moment and its lecturer can no longer leave it.
    started_at timestamptz,
    started_by integer    REFERENCES users (id),
    CHECK (started_at IS NULL OR started_by IS NOT NULL),
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by integer    REFERENCES users (id)
);

-- Course assignment. UNIQUE (course_id): a class has at most one lecturer.
CREATE TABLE course_lecturers (
    course_id   integer     NOT NULL UNIQUE REFERENCES courses (id),
    lecturer_id integer     NOT NULL REFERENCES users (id),
    assigned_by integer     REFERENCES users (id),
    assigned_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (course_id, lecturer_id)
);

CREATE TABLE enrollments (
    id          serial      PRIMARY KEY,
    student_id  integer     NOT NULL REFERENCES students (id),
    course_id   integer     NOT NULL REFERENCES courses (id),
    status      varchar(10) NOT NULL DEFAULT 'ENROLLED' CHECK (status IN ('ENROLLED', 'DROPPED')),
    enrolled_at timestamptz NOT NULL DEFAULT now(),
    enrolled_by integer     REFERENCES users (id),
    UNIQUE (student_id, course_id)
);

CREATE TABLE grades (
    id            serial       PRIMARY KEY,
    enrollment_id integer      NOT NULL UNIQUE REFERENCES enrollments (id),
    -- Four grade components on a 0-10 scale; NULL = not graded yet.
    process1      numeric(4,2) CHECK (process1 BETWEEN 0 AND 10),    -- weight 10 %
    process2      numeric(4,2) CHECK (process2 BETWEEN 0 AND 10),    -- weight 20 %
    midterm       numeric(4,2) CHECK (midterm BETWEEN 0 AND 10),     -- weight 20 %
    final_exam    numeric(4,2) CHECK (final_exam BETWEEN 0 AND 10),  -- weight 50 %
    -- Course total, computed by the database (cannot be written directly);
    -- NULL until all four components are recorded.
    score         numeric(4,2) GENERATED ALWAYS AS
                  (round(process1 * 0.10 + process2 * 0.20 + midterm * 0.20 + final_exam * 0.50, 2)) STORED,
    CHECK (coalesce(process1, process2, midterm, final_exam) IS NOT NULL),
    created_at    timestamptz  NOT NULL DEFAULT now(),
    created_by    integer      NOT NULL REFERENCES users (id),
    updated_at    timestamptz  NOT NULL DEFAULT now(),
    updated_by    integer      NOT NULL REFERENCES users (id)
);

-- -----------------------------------------------------------------------------
-- 4. Security audit log (append-only + SHA-256 hash chain)
-- -----------------------------------------------------------------------------
CREATE SEQUENCE audit_logs_id_seq;

CREATE TABLE audit_logs (
    id              bigint      PRIMARY KEY,           -- assigned by trigger
    ts              timestamptz NOT NULL,              -- assigned by trigger
    actor_user_id   integer,
    actor_username  varchar(64),
    event_type      varchar(40) NOT NULL,
    target_resource varchar(120),
    result          varchar(10) NOT NULL CHECK (result IN ('SUCCESS', 'DENIED', 'FAILURE')),
    details         jsonb       NOT NULL DEFAULT '{}'::jsonb,
    source_ip       varchar(45),
    prev_hash       char(64)    NOT NULL,              -- assigned by trigger
    entry_hash      char(64)    NOT NULL               -- assigned by trigger
);
CREATE INDEX audit_logs_event_idx ON audit_logs (event_type);
CREATE INDEX audit_logs_actor_idx ON audit_logs (actor_username);

CREATE FUNCTION audit_compute_hash(
    p_prev text, p_id bigint, p_ts timestamptz, p_actor_id integer, p_actor text,
    p_event text, p_target text, p_result text, p_details jsonb, p_ip text)
RETURNS text LANGUAGE sql STABLE AS $$
    SELECT encode(sha256(convert_to(concat_ws('|',
        p_prev,
        p_id::text,
        to_char(p_ts AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
        coalesce(p_actor_id::text, ''),
        coalesce(p_actor, ''),
        p_event,
        coalesce(p_target, ''),
        p_result,
        p_details::text,
        coalesce(p_ip, '')), 'UTF8')), 'hex')
$$;

-- Assigns id, timestamp and hash-chain values. The client cannot choose them.
-- The advisory lock serialises writers so that ids follow chain order.
CREATE FUNCTION audit_logs_before_insert() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    v_prev text;
BEGIN
    PERFORM pg_advisory_xact_lock(727274);
    NEW.id := nextval('audit_logs_id_seq');
    NEW.ts := clock_timestamp();
    NEW.details := coalesce(NEW.details, '{}'::jsonb);
    SELECT entry_hash INTO v_prev FROM audit_logs ORDER BY id DESC LIMIT 1;
    NEW.prev_hash := coalesce(v_prev, repeat('0', 64));
    NEW.entry_hash := audit_compute_hash(NEW.prev_hash, NEW.id, NEW.ts, NEW.actor_user_id,
        NEW.actor_username, NEW.event_type, NEW.target_resource, NEW.result,
        NEW.details, NEW.source_ip);
    RETURN NEW;
END $$;

CREATE FUNCTION audit_logs_block_modification() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit_logs is append-only: % is not allowed', TG_OP
        USING ERRCODE = '42501';
END $$;

CREATE TRIGGER audit_logs_chain BEFORE INSERT ON audit_logs
    FOR EACH ROW EXECUTE FUNCTION audit_logs_before_insert();
CREATE TRIGGER audit_logs_no_update BEFORE UPDATE OR DELETE ON audit_logs
    FOR EACH ROW EXECUTE FUNCTION audit_logs_block_modification();
CREATE TRIGGER audit_logs_no_truncate BEFORE TRUNCATE ON audit_logs
    FOR EACH STATEMENT EXECUTE FUNCTION audit_logs_block_modification();

-- Recomputes the whole chain. Returns the number of entries checked and the id
-- of the first entry whose hash does not match (NULL when the chain is intact).
CREATE FUNCTION audit_verify_chain()
RETURNS TABLE (checked bigint, first_bad_id bigint) LANGUAGE plpgsql STABLE AS $$
DECLARE
    r      record;
    v_prev text := repeat('0', 64);
    v_n    bigint := 0;
BEGIN
    FOR r IN SELECT * FROM audit_logs ORDER BY id LOOP
        v_n := v_n + 1;
        IF r.prev_hash <> v_prev OR r.entry_hash <> audit_compute_hash(r.prev_hash, r.id, r.ts,
               r.actor_user_id, r.actor_username, r.event_type, r.target_resource,
               r.result, r.details, r.source_ip) THEN
            checked := v_n; first_bad_id := r.id;
            RETURN NEXT;
            RETURN;
        END IF;
        v_prev := r.entry_hash;
    END LOOP;
    checked := v_n; first_bad_id := NULL;
    RETURN NEXT;
END $$;

-- -----------------------------------------------------------------------------
-- 5. Integrity triggers (defence in depth behind the application checks)
-- -----------------------------------------------------------------------------

-- Separation of duties: reject a role assignment that conflicts with a role
-- the user already holds.
CREATE FUNCTION user_roles_conflict_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM user_roles ur
          JOIN role_conflicts rc
            ON (rc.role_a = ur.role_id AND rc.role_b = NEW.role_id)
            OR (rc.role_b = ur.role_id AND rc.role_a = NEW.role_id)
         WHERE ur.user_id = NEW.user_id) THEN
        RAISE EXCEPTION 'role conflict (separation of duties)' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER user_roles_conflict BEFORE INSERT ON user_roles
    FOR EACH ROW EXECUTE FUNCTION user_roles_conflict_guard();

-- A grade may only be written by an active LECTURER assigned to the course of
-- the enrollment, never for the lecturer's own enrollment, and only while the
-- enrollment is active. created_* columns cannot be rewritten on update.
CREATE FUNCTION grades_write_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    v_course       integer;
    v_status       text;
    v_student_user integer;
BEGIN
    SELECT e.course_id, e.status, s.user_id
      INTO v_course, v_status, v_student_user
      FROM enrollments e
      JOIN students s ON s.id = e.student_id
     WHERE e.id = NEW.enrollment_id;

    IF v_status IS DISTINCT FROM 'ENROLLED' THEN
        RAISE EXCEPTION 'grade_guard: enrollment is not active' USING ERRCODE = '42501';
    END IF;
    IF NOT EXISTS (
        SELECT 1
          FROM course_lecturers cl
          JOIN users u       ON u.id = cl.lecturer_id AND u.is_active
          JOIN user_roles ur ON ur.user_id = u.id
          JOIN roles r       ON r.id = ur.role_id AND r.name = 'LECTURER'
         WHERE cl.course_id = v_course AND cl.lecturer_id = NEW.updated_by) THEN
        RAISE EXCEPTION 'grade_guard: writer is not an assigned lecturer' USING ERRCODE = '42501';
    END IF;
    IF v_student_user IS NOT NULL AND v_student_user = NEW.updated_by THEN
        RAISE EXCEPTION 'grade_guard: self-grading is not allowed' USING ERRCODE = '42501';
    END IF;

    IF TG_OP = 'UPDATE' THEN
        NEW.enrollment_id := OLD.enrollment_id;
        NEW.created_at    := OLD.created_at;
        NEW.created_by    := OLD.created_by;
    END IF;
    NEW.updated_at := now();
    RETURN NEW;
END $$;

CREATE TRIGGER grades_guard BEFORE INSERT OR UPDATE ON grades
    FOR EACH ROW EXECUTE FUNCTION grades_write_guard();

-- A class holds at most `capacity` (<= 30) active students. The course row is
-- locked so that concurrent enrollments cannot exceed the limit.
CREATE FUNCTION enrollments_capacity_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    v_capacity smallint;
    v_active   integer;
BEGIN
    IF NEW.status <> 'ENROLLED' OR (TG_OP = 'UPDATE' AND OLD.status = 'ENROLLED') THEN
        RETURN NEW;
    END IF;
    SELECT capacity INTO v_capacity FROM courses WHERE id = NEW.course_id FOR UPDATE;
    SELECT count(*) INTO v_active FROM enrollments
     WHERE course_id = NEW.course_id AND status = 'ENROLLED' AND id <> NEW.id;
    IF v_active >= v_capacity THEN
        RAISE EXCEPTION 'class is full (capacity %)', v_capacity USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER enrollments_capacity BEFORE INSERT OR UPDATE OF status ON enrollments
    FOR EACH ROW EXECUTE FUNCTION enrollments_capacity_guard();

-- Only an active user holding the LECTURER role can be assigned to a class.
CREATE FUNCTION course_lecturers_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM users u
          JOIN user_roles ur ON ur.user_id = u.id
          JOIN roles r ON r.id = ur.role_id AND r.name = 'LECTURER'
         WHERE u.id = NEW.lecturer_id AND u.is_active) THEN
        RAISE EXCEPTION 'course_lecturers: user is not an active lecturer' USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER course_lecturers_role BEFORE INSERT OR UPDATE ON course_lecturers
    FOR EACH ROW EXECUTE FUNCTION course_lecturers_guard();

-- -----------------------------------------------------------------------------
-- 6. Least-privilege grants for the application account
-- -----------------------------------------------------------------------------
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO uni_app;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;

-- Access-control configuration is read-only for the application.
GRANT SELECT ON roles, permissions, role_permissions, role_conflicts TO uni_app;

-- Accounts: no DELETE (accounts are disabled, not removed); username and
-- created_* columns cannot be changed.
GRANT SELECT, INSERT ON users TO uni_app;
GRANT UPDATE (password_hash, full_name, is_active, failed_login_count, locked_until,
              must_change_password, password_expires_at, updated_at)
    ON users TO uni_app;
-- Reset requests: no DELETE; only the workflow columns can change.
GRANT SELECT, INSERT ON password_reset_requests TO uni_app;
GRANT UPDATE (status, reply_message, resolved_at, resolved_by, delivered_at) ON password_reset_requests TO uni_app;
GRANT SELECT, INSERT, DELETE ON user_roles TO uni_app;
GRANT SELECT, INSERT, DELETE ON sessions TO uni_app;
GRANT UPDATE (last_seen_at, revoked_at) ON sessions TO uni_app;

-- Academic data: no DELETE anywhere; courses and assignments are read-only.
GRANT SELECT, INSERT ON students TO uni_app;
GRANT UPDATE (full_name, date_of_birth, program, email, phone, address, updated_at, updated_by)
    ON students TO uni_app;
-- Classes are created by the registrar; code, id and audit columns cannot be changed.
GRANT SELECT, INSERT ON courses TO uni_app;
GRANT UPDATE (title, capacity, is_locked, started_at, started_by) ON courses TO uni_app;
GRANT SELECT, INSERT, DELETE ON course_lecturers TO uni_app;
GRANT SELECT, INSERT ON enrollments TO uni_app;
GRANT UPDATE (status) ON enrollments TO uni_app;
GRANT SELECT, INSERT ON grades TO uni_app;
GRANT UPDATE (process1, process2, midterm, final_exam, updated_by, updated_at) ON grades TO uni_app;

-- Audit log: append and read only.
GRANT SELECT, INSERT ON audit_logs TO uni_app;

GRANT USAGE ON SEQUENCE password_reset_requests_id_seq, users_id_seq, students_id_seq, enrollments_id_seq, grades_id_seq, courses_id_seq,
    audit_logs_id_seq TO uni_app;

COMMIT;

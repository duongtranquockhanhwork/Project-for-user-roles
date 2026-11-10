-- =============================================================================
-- University Records System - seed data
--
-- DEMO DATA ONLY. Every demo account uses the password pattern
--     <username>@Demo2026        e.g. student01 -> student01@Demo2026
-- Only Argon2id hashes are stored here. Change or remove these accounts
-- before any real deployment.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Roles
-- -----------------------------------------------------------------------------
INSERT INTO roles (id, name, description) VALUES
    (1, 'STUDENT',   'Views own profile, enrollment and grades; updates own contact information'),
    (2, 'LECTURER',  'Views students of assigned courses; creates and updates grades for assigned courses'),
    (3, 'REGISTRAR', 'Creates and updates student records; manages enrollment; views grades'),
    (4, 'AUDITOR',   'Reads audit logs and the access-control configuration (read-only)'),
    (5, 'ADMIN',     'Manages user accounts and role assignments; no access to academic records');

-- -----------------------------------------------------------------------------
-- Permissions (the access-control matrix in machine-readable form)
-- -----------------------------------------------------------------------------
INSERT INTO permissions (code, description) VALUES
    ('profile.read',           'View a student profile'),
    ('profile.update_contact', 'Update contact information (email, phone, address) of a student profile'),
    ('student.search',         'List and search student records'),
    ('student.create',         'Create a student record'),
    ('student.update',         'Update a student record'),
    ('course.read',            'View course information'),
    ('roster.read',            'View the list of students enrolled in a course'),
    ('enrollment.read',        'View enrollments'),
    ('enrollment.manage',      'Create or drop enrollments'),
    ('course.manage',          'Create classes and assign or remove their lecturer'),
    ('class.join',             'Browse the class catalog and join or leave a class as a student'),
    ('class.teach',            'Browse the class catalog and take an unassigned class as its lecturer'),
    ('grade.read',             'View grades'),
    ('grade.write',            'Create or update grades'),
    ('audit.read',             'Read security audit logs and verify their integrity'),
    ('policy.read',            'Read the access-control configuration'),
    ('user.read',              'List user accounts'),
    ('user.manage',            'Create, disable and enable user accounts'),
    ('role.assign',            'Assign or remove roles'),
    ('account.rename',         'Change the display name of one''s own account'),
    ('password_reset.manage',  'Review and answer forgotten-password requests');

INSERT INTO role_permissions (role_id, permission_code, scope) VALUES
    -- STUDENT: own records only
    (1, 'profile.read',           'OWN'),
    (1, 'profile.update_contact', 'OWN'),
    (1, 'enrollment.read',        'OWN'),
    (1, 'grade.read',             'OWN'),
    (1, 'class.join',             'OWN'),
    (1, 'account.rename',         'OWN'),
    -- LECTURER: only courses assigned to the lecturer
    (2, 'course.read',            'ASSIGNED'),
    (2, 'roster.read',            'ASSIGNED'),
    (2, 'profile.read',           'ASSIGNED'),
    (2, 'grade.read',             'ASSIGNED'),
    (2, 'grade.write',            'ASSIGNED'),
    (2, 'class.teach',            'OWN'),
    (2, 'account.rename',         'OWN'),
    -- REGISTRAR: all student records, no grade.write
    (3, 'student.search',         'ALL'),
    (3, 'student.create',         'ALL'),
    (3, 'student.update',         'ALL'),
    (3, 'profile.read',           'ALL'),
    (3, 'course.read',            'ALL'),
    (3, 'roster.read',            'ALL'),
    (3, 'enrollment.read',        'ALL'),
    (3, 'enrollment.manage',      'ALL'),
    (3, 'course.manage',          'ALL'),
    (3, 'grade.read',             'ALL'),
    -- AUDITOR: read-only security data
    (4, 'audit.read',             'ALL'),
    (4, 'policy.read',            'ALL'),
    -- ADMIN: accounts and roles only, no academic permissions
    (5, 'user.read',              'ALL'),
    (5, 'user.manage',            'ALL'),
    (5, 'role.assign',            'ALL'),
    (5, 'password_reset.manage',  'ALL');

INSERT INTO role_conflicts (role_a, role_b, reason) VALUES
    (1, 3, 'A registrar must not maintain his or her own student record or enrollment'),
    (2, 3, 'Enrolling students and grading them must be performed by different people'),
    (4, 5, 'The person who manages accounts must not be the one who audits those actions');

-- -----------------------------------------------------------------------------
-- Demo user accounts (password = <username>@Demo2026, Argon2id m=64MiB t=3 p=4)
-- -----------------------------------------------------------------------------
INSERT INTO users (username, password_hash, full_name, is_active) VALUES
    ('admin01',     '$argon2id$v=19$m=65536,t=3,p=4$70Mr8Rc+SF7a7Ddqrg3GSA$XQtVOUsPiGwDOi8Ltd4AWt8mA618ftCNhMJHmTT2KA0', 'Alice Admin',        true),
    ('admin02',     '$argon2id$v=19$m=65536,t=3,p=4$gKBNqgEcyouNQJBWSQK8uQ$9VHaUexWkKrYA55ks1XDdP9DavNyf9bkMFYBphnlVDQ', 'Adam Admin',         true),
    ('registrar01', '$argon2id$v=19$m=65536,t=3,p=4$1VUX0Z+119jqet1CXabFig$Q/BE5feXaJwaW4OYjnXW68OArH5P+cKoJqzzimGjl5k', 'Rita Registrar',     true),
    ('auditor01',   '$argon2id$v=19$m=65536,t=3,p=4$qejmdKx4aKAOnXfeZEg+4A$V7wSimzfxLIPgnA+9Ul1ZbRgKiq6Xn/CjyrOtjk6/Lk', 'Oscar Auditor',      true),
    ('lecturer01',  '$argon2id$v=19$m=65536,t=3,p=4$QsOlzSFx5fqx3g75p9CYMw$CWutPbKLPKGCPVA1Go32iIFZ3GCbtQVQUMJCWgEv+kc', 'Dr. Linh Lecturer',  true),
    ('lecturer02',  '$argon2id$v=19$m=65536,t=3,p=4$Ndoh/kz8LXmpBPXtcrwH2A$5L0LtCy9Bjsz3ikQsiYPImJHOJKwqK73RAJgh+sSXEQ', 'Dr. Minh Lecturer',  true),
    ('ta01',        '$argon2id$v=19$m=65536,t=3,p=4$of8CStEkJIL9Z1BFOkDAYQ$5YVItgIWZNbr5q8ng6IfH4ix1ZroJ9TITZoWjxkiwXE', 'Tuan Teaching-Assistant', true),
    ('student01',   '$argon2id$v=19$m=65536,t=3,p=4$5Z8W9+5GhpKPhHGfJVGGkw$9XuDE7m6n4WZxp0UQhwGjBdDhuqzfm5sMpBxM+hkpI8', 'Nguyen Van An',      true),
    ('student02',   '$argon2id$v=19$m=65536,t=3,p=4$/QwBec2MZ9Yao6xxRRQrow$6nBlxvgfggoR9zDzw/uDY2D3h+yIpTb/IaTjjoFGPv4', 'Tran Thi Binh',      true),
    ('student03',   '$argon2id$v=19$m=65536,t=3,p=4$3vRfv4RQ3gnHvtMcLaOtYQ$gK7cD2UIQPHc6xSckateTBDRDpCY2wKMKx3aa0tcoeo', 'Le Van Cuong',       true),
    ('disabled01',  '$argon2id$v=19$m=65536,t=3,p=4$T4/n2JQ0+oroO7HxfPtFDA$O0VTBZyAvfiJCXzxR96/WV3leE6aN8e7feohNLNPNvs', 'Pham Disabled',      false);

INSERT INTO user_roles (user_id, role_id)
SELECT u.id, r.id
  FROM (VALUES
        ('admin01', 'ADMIN'), ('admin02', 'ADMIN'),
        ('registrar01', 'REGISTRAR'),
        ('auditor01', 'AUDITOR'),
        ('lecturer01', 'LECTURER'), ('lecturer02', 'LECTURER'),
        ('ta01', 'STUDENT'), ('ta01', 'LECTURER'),          -- multi-role user
        ('student01', 'STUDENT'), ('student02', 'STUDENT'), ('student03', 'STUDENT'),
        ('disabled01', 'STUDENT')) AS v (username, role_name)
  JOIN users u ON u.username = v.username
  JOIN roles r ON r.name = v.role_name;

-- -----------------------------------------------------------------------------
-- Courses and lecturer assignment
-- -----------------------------------------------------------------------------
INSERT INTO courses (code, title, credits, semester, capacity) VALUES
    ('IS101', 'Information Security',  3, '2026-1', 30),
    ('DB201', 'Database Systems',      3, '2026-1', 30),
    ('NW301', 'Computer Networks',     3, '2026-1', 30),
    ('SE202', 'Software Engineering',  3, '2026-1', 30),
    ('AI305', 'Artificial Intelligence', 3, '2026-1', 30);   -- open class, no lecturer yet

-- One lecturer per class. ta01 (Student + Lecturer) teaches SE202 and is also
-- enrolled in it: this legacy record demonstrates the self-grading guard.
INSERT INTO course_lecturers (course_id, lecturer_id)
SELECT c.id, u.id
  FROM (VALUES ('IS101', 'lecturer01'), ('DB201', 'lecturer01'),
               ('NW301', 'lecturer02'), ('SE202', 'ta01')) AS v (course_code, username)
  JOIN courses c ON c.code = v.course_code
  JOIN users u   ON u.username = v.username;

-- -----------------------------------------------------------------------------
-- Student profiles
-- -----------------------------------------------------------------------------
INSERT INTO students (user_id, student_code, full_name, date_of_birth, program, email, phone, address)
SELECT u.id, v.code, v.full_name, v.dob::date, v.program, v.email, v.phone, v.address
  FROM (VALUES
        ('student01',  'S2026001', 'Nguyen Van An',  '2005-03-14', 'Information Technology', 'an.nguyen@student.example.edu',   '0901000001', '12 Le Loi, District 1, HCMC'),
        ('student02',  'S2026002', 'Tran Thi Binh',  '2005-07-02', 'Information Technology', 'binh.tran@student.example.edu',   '0901000002', '45 Nguyen Hue, District 1, HCMC'),
        ('student03',  'S2026003', 'Le Van Cuong',   '2004-11-21', 'Computer Science',       'cuong.le@student.example.edu',    '0901000003', '7 Tran Hung Dao, District 5, HCMC'),
        ('ta01',       'S2026004', 'Tuan Teaching-Assistant', '2003-01-30', 'Computer Science', 'tuan.ta@student.example.edu', '0901000004', '88 Hai Ba Trung, District 3, HCMC'),
        ('disabled01', 'S2026005', 'Pham Disabled',  '2005-05-05', 'Information Technology', 'disabled@student.example.edu',    '0901000005', '1 Vo Van Tan, District 3, HCMC')
       ) AS v (username, code, full_name, dob, program, email, phone, address)
  JOIN users u ON u.username = v.username
 ORDER BY v.code;

-- A student profile that has no login account yet.
INSERT INTO students (student_code, full_name, date_of_birth, program, email)
VALUES ('S2026006', 'Hoang Thi Dung', '2005-09-09', 'Information Systems', 'dung.hoang@student.example.edu');

-- -----------------------------------------------------------------------------
-- Enrollments
-- -----------------------------------------------------------------------------
INSERT INTO enrollments (student_id, course_id)
SELECT s.id, c.id
  FROM (VALUES ('S2026001', 'IS101'), ('S2026001', 'NW301'),
               ('S2026002', 'IS101'), ('S2026002', 'DB201'),
               ('S2026003', 'DB201'), ('S2026003', 'NW301'),
               ('S2026004', 'IS101'), ('S2026004', 'NW301'),
               ('S2026003', 'SE202'), ('S2026004', 'SE202'),
               ('S2026006', 'DB201')) AS v (student_code, course_code)
  JOIN students s ON s.student_code = v.student_code
  JOIN courses c  ON c.code = v.course_code
 ORDER BY v.student_code, v.course_code;

-- -----------------------------------------------------------------------------
-- Grades (written by the assigned lecturer, so the grade guard trigger passes)
-- -----------------------------------------------------------------------------
-- Components: process 1 (10 %), process 2 (20 %), midterm (20 %), final (50 %).
-- The course total (grades.score) is computed by the database.
INSERT INTO grades (enrollment_id, process1, process2, midterm, final_exam, created_by, updated_by)
SELECT e.id, v.p1, v.p2, v.mid, v.fin, u.id, u.id
  FROM (VALUES ('S2026001', 'IS101', 9.00, 8.50, 8.00, 8.50, 'lecturer01'),
               ('S2026001', 'NW301', 7.00, 6.00, 6.50, 6.50, 'lecturer02'),
               ('S2026002', 'IS101', 8.00, 7.00, 6.50, 7.00, 'lecturer01'),
               ('S2026002', 'DB201', 9.50, 9.00, 8.50, 9.00, 'lecturer01'),
               ('S2026004', 'IS101', 8.00, 8.50, 7.50, 8.00, 'lecturer01'),
               ('S2026004', 'NW301', 8.00, 7.50, 7.00, NULL, 'lecturer02'))
       AS v (student_code, course_code, p1, p2, mid, fin, lecturer)
  JOIN students s    ON s.student_code = v.student_code
  JOIN courses c     ON c.code = v.course_code
  JOIN enrollments e ON e.student_id = s.id AND e.course_id = c.id
  JOIN users u       ON u.username = v.lecturer;

-- First audit entry: marks the start of the hash chain.
INSERT INTO audit_logs (actor_username, event_type, target_resource, result, details)
VALUES ('system', 'SYSTEM_INITIALISED', 'database', 'SUCCESS', '{"note": "seed data loaded"}');

COMMIT;

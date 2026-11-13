# University Records System: Design, Implement, and Audit Secure Access Control

**Course:** Introduction to Information Security, Faculty of Information Technology, Ton Duc Thang University (academic year 2026–2027)
**Instructor:** Ph.D Huynh Ngoc Tu

| Member | Student ID | Primary responsibility |
|---|---|---|
| Trieu Ngoc Van Anh | 524H0005 | Threat modeling and access-control design |
| Duong Tran Quoc Khanh | 523H0040 | Authentication, authorization and implementation |
| Nguyen Vo Thanh Tu | 523H0189 | Database security, testing and audit logging |

This project is a web-based University Records System. It manages users, student profiles, classes, enrollments,
grades (four weighted components) and a security audit log, and it enforces role-based access control for five
roles: Student, Lecturer, Registrar, Security Auditor and System Administrator. Students can register themselves
and join classes; each class has one lecturer and at most 30 students. Every user can change their password on
**My account**, and forgotten passwords are reset through a request that an administrator approves. Authorization is enforced on the server at three layers: an endpoint
permission check, a record-level ownership or course-assignment check, and database privileges and triggers.

---

## 1. Submission contents

<!-- tree:start -->
The project folder follows the layout required by the assignment (rename it to `ClassID_GroupID_StudentID`
or build the archive with `tools/package_submission.py`, see Section 7):

```
ClassID_GroupID_StudentID/
├── README.md               ← this file (how to run and grade the project)
├── report/               ← report.pdf (written report), report.docx, Kich_ban_demo.docx (demo script), assignment PDF
├── demo-video-link.txt     ← link to the demonstration video
├── source/                 ← Flask application (source/README.md = technical documentation)
├── database/
│   ├── schema.sql          ← tables, constraints, triggers, grants
│   ├── seed-data.sql       ← roles, permissions, demo accounts and data
│   └── init/               ← creates the least-privilege DB role
├── tests/                  ← 62 automated security tests (pytest) + screenshot script
├── evidence/               ← test results, HTTP traces, screenshots
├── contribution/           ← member-a.pdf, member-b.pdf, member-c.pdf (+ editable .md sources)
├── docker-compose.yml      ← starts the database and the web application
├── .env.example            ← template for the secrets file
├── docs/                   ← DFD, report and contribution builders, group information
└── tools/                  ← package_submission.py (creates the submission .zip)
```
<!-- tree:end -->

---

## 2. Run the application

**Requirement:** Docker Desktop (Windows, macOS or Linux) with Docker Compose v2. Nothing else is needed to run the system.

**Step 1.** Open a terminal in the project folder (the folder that contains this README).

**Step 2.** Create the secrets file from the template. This step is not needed if `.env` already exists.

```bash
cp .env.example .env
```

Open `.env` and replace the three `change-me-...` values with any long random strings. For example, run this
command three times and copy each output into one value:

```bash
python -c "import secrets; print(secrets.token_urlsafe(24))"
```

**Step 3.** Build and start the containers. The first start creates the database from `database/schema.sql` and
`database/seed-data.sql`.

```bash
docker compose up -d --build
```

**Step 4.** Open **http://localhost:8000** in a browser.

> **If the login page says the database is not ready or every login fails** (the log of `db` shows
> `relation "users" does not exist`), the database volume was created by an earlier, failed start. Remove it
> with `docker compose down -v` and run `docker compose up -d --build` again: the database is only initialised
> when its volume is empty.

To reset the system to the original seed data at any time (this deletes all changes):

```bash
docker compose down -v
```

```bash
docker compose up -d
```

---

## 3. Accounts for grading

All accounts below are created by `database/seed-data.sql`. Every password follows the pattern
`<username>@Demo2026`. These are demo credentials for local grading only.

| Username | Password | Role(s) | What this account can do |
|---|---|---|---|
| `student01` | `student01@Demo2026` | STUDENT | Own profile, enrollments and grades (S2026001: IS101, NW301); update own contact info; join/leave classes |
| `student02` | `student02@Demo2026` | STUDENT | Same, for S2026002 (IS101, DB201) |
| `student03` | `student03@Demo2026` | STUDENT | Same, for S2026003 (DB201, NW301, SE202) |
| `lecturer01` | `lecturer01@Demo2026` | LECTURER | Rosters and grade components of **IS101** and **DB201** only |
| `lecturer02` | `lecturer02@Demo2026` | LECTURER | Roster and grades of **NW301**; can take the unassigned class **AI305** |
| `ta01` | `ta01@Demo2026` | STUDENT + LECTURER | Multiple roles: student S2026004 and lecturer of SE202; cannot grade their own SE202 enrollment |
| `registrar01` | `registrar01@Demo2026` | REGISTRAR | Student records, enrollments, **create classes and assign their lecturer/students**, view grades; **cannot modify grades** |
| `auditor01` | `auditor01@Demo2026` | AUDITOR | Read the audit log, verify its integrity, read the access-control configuration (read-only) |
| `admin01` | `admin01@Demo2026` | ADMIN | Create, disable, enable and unlock users; assign and remove roles; **no access to academic data** |
| `admin02` | `admin02@Demo2026` | ADMIN | Second administrator (role changes on another admin require a second admin) |
| `disabled01` | `disabled01@Demo2026` | STUDENT (disabled) | Login must be **rejected** |

**New accounts:** anyone can create a student account at **http://localhost:8000/register** (link "Create an
account" on the sign-in page). Such an account always receives only the STUDENT role and a new student profile.

**Password changes and resets:** every account can change its password on **My account** (students and
lecturers can also change their name). A forgotten password is requested with **Forgot password?** on the sign-in
page; the requester receives a reference code, `admin01` approves or rejects the request under **Password
requests**, and the requester then reveals a one-time temporary password (valid 24 h) that must be changed at the
next login. Passwords are stored only as Argon2id hashes, so **no one, including the administrator, can view a
user's password**; the administrator never sees the temporary password either.

Database accounts are not needed for grading through the browser. The database uses the DBA account `uni_dba` and the
least-privilege application account `uni_app`, whose passwords are the values you set in `.env`.

> After 5 wrong passwords an account is locked for 15 minutes. To unlock it, log in as `admin01` and click
> **Unlock** on *Users & roles*, or reset the database with `docker compose down -v`.

### What each role does

| Role | Main duties in the system | Explicitly not allowed |
|---|---|---|
| **Student** | View own profile, enrollments, the four grade components, course totals and overall average; update own e-mail/phone/address; join a class with free seats or leave it before grades exist | Other students' records, changing grades, creating classes |
| **Lecturer** | See the classes they teach, their rosters and students; enter process 1 (10 %), process 2 (20 %), midterm (20 %) and final (50 %); take a class that has no lecturer; **close/reopen enrollment and start** their class; leave the class before it starts; remove students once it has started | Grading classes they do not teach or their own enrollment; leaving a class after it has started; arranging other classes |
| **Registrar** | Academic office: create/update student records, **create classes** (≤ 30 students), assign/replace/remove the class lecturer, add/remove students **at any time** (even when enrollment is closed), lock/unlock/start any class, manage enrollments, view grades | Modifying grades |
| **Security Auditor** | Read the audit log, verify its hash chain, read the access-control configuration | Changing any data |
| **System Administrator** | Create/disable/enable/unlock accounts, assign/remove roles, **answer forgotten-password requests** | Any academic data; viewing passwords; changing own roles; approving own reset |
| **Every role** | **My account**: change own password (current password required). Students and lecturers can also change their name | Registrar, Auditor and Administrator cannot rename themselves |

---

## 4. Suggested grading scenarios

Each row corresponds to a test in the report. After each scenario, log in as `auditor01` and open **Audit log** to
see the recorded event.

| # | Log in as | Action | Expected result |
|---|---|---|---|
| 1 | `student01` with a wrong password | Submit the login form | "Invalid username or password." (same message as for an unknown user) |
| 2 | `disabled01` | Log in with the correct password | Rejected with the same generic message |
| 3 | `student01` | **My profile → Grades** (`/students/1/grades`) | Own grades are shown |
| 4 | `student01` | Change the URL to `/students/2/grades` | **403** – another student's record (IDOR blocked, logged as RECORD_ACCESS_DENIED) |
| 5 | `lecturer01` | **My courses → IS101**, enter the four components of a student and click Save | "Grade saved"; total = 10/20/20/50 % weighted; logged as GRADE_UPDATE |
| 6 | `lecturer01` | Open `/courses/3/roster` (NW301, not assigned) | **403** |
| 7 | `registrar01` | **Enrollments** → enroll `S2026006` in IS101 or NW301 | Enrollment created (ENROLLMENT_CREATE) |
| 8 | `admin01` | Open `/students/1/grades` | **403** – the administrator has no academic access |
| 9 | `admin01` | **Users & roles** → assign AUDITOR to `admin02` | **403** – role conflict (separation of duties) |
| 10 | `admin01` | **Users & roles** → assign a role to a non-admin user | Allowed and logged as ROLE_ASSIGN |
| 11 | any | Log in with username `' OR '1'='1' --` | Generic failure, no database error |
| 12 | `student01` | Save the address `<script>alert('xss')</script>` | The text is displayed as typed; no script runs |
| 13 | `auditor01` | **Audit log → Verify integrity** | "Hash chain intact" |
| 14 | `student01` | Click the logout icon (top right), then press Back and reload | Session rejected (**401**) |
| 15 | (no login) | **Create an account** on the sign-in page, then log in | New account has only the STUDENT role and a new student code |
| 16 | new student | **Class catalog → Join class** (e.g. AI305) | Joined; seat counter increases; CLASS_JOIN logged |
| 17 | `registrar01` | **Courses → New class** (capacity 30, choose a lecturer), then add students on the class page | Class created; at most 1 lecturer and 30 students |
| 18 | `lecturer02` | **Class catalog → Teach this class** on AI305 | Becomes the only lecturer of AI305 |
| 19 | `student01` | **My grades** | All four components, totals and the credit-weighted overall average |
| 20 | any role | **My account → Change password** (enter a wrong current password first) | Wrong current password rejected; change succeeds; other sessions signed out |
| 21 | `registrar01` | **My account** | Name field locked (staff); password change available |
| 22 | (no login) | **Forgot password?** for `student02` → note the reference code | "Request received" with a one-time reference code |
| 23 | `admin01` | **Password requests** → Approve with a reply | Request approved; no password is shown to the admin |
| 24 | (no login) | **I already have a reference code** → Reveal temporary password → sign in with it | Shown once; sign-in leads to a forced password change |
| 25 | `student01` | **Class catalog**: DB201 shows *Closed* (the class has started) | No Join button; a forced join request returns **403** |
| 26 | `lecturer02` | **Class catalog → Teach this class** on AI305 → open the class → **Leave this class** | Allowed, because AI305 has not started |
| 27 | `lecturer01` | **My courses → IS101 → Class status**: Open/Close enrollment; on a started class try **Leave** (not shown) | Enrollment toggles; leaving a started class is impossible (only the registrar can remove the lecturer) |
| 28 | `lecturer01` | In IS101 (started) click the bin icon next to a student | Student removed (DROPPED); not possible before a class starts |

Scenarios 3–6 use the seed ids: student01 = `/students/1`, student02 = `/students/2`, IS101 = course 1,
DB201 = course 2, NW301 = course 3, SE202 = course 4, AI305 = course 5.

---

## 5. Run the automated security tests (optional)

**Requirements:** Python 3.11+ and the running containers from Section 2.

```bash
python -m pip install -r tests/requirements.txt
```

```bash
python -m pytest tests
```

The suite has 62 tests (mandatory T01–T20 plus original T21–T62). The results are written to
`evidence/test-results.html`, one request/response trace per test to `evidence/http/`, and the
screenshots to `evidence/screenshots/`. To regenerate the screenshots (Microsoft Edge must be installed),
run:

```bash
python tests/capture_screenshots.py
```

---

## 6. Report and video

* Written report: [`report/report.pdf`](report/report.pdf). Chapters 1–9 are the main body (10 pages);
  Appendix A is the system demonstration (every screen, by role), Appendix B the complete test table and
  Appendix C the requirement traceability; References are the last section.
* Demonstration video: see [`demo-video-link.txt`](demo-video-link.txt); the recording script is `report/Kich_ban_demo.docx`.
* Individual contribution statements: `contribution/member-a.pdf`, `member-b.pdf` and `member-c.pdf`.

---

## 7. Build the submission package

Add the repository link to `contribution/member-*.md` (section 2, "Repository commits") and rebuild the
statements:

```bash
python docs/build_contributions.py
```


Fill in `class_id` and `group_id` in `docs/group.json`, then run:

```bash
python tools/package_submission.py --student-id 523H0040
```

The script checks that every required item exists and creates `dist/ClassID_GroupID_StudentID.zip`. It never
includes `.env`, the `.git` folder or caches.

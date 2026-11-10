# Demo video script (target ≤ 8 minutes)

Prepare beforehand: run `docker compose down -v` and then `docker compose up -d --build` for a clean seed state.
Open two browser windows (a normal and a private window) so that two users can be logged in at the same time.

| # | Time | Required item | What to show / say |
|---|------|---------------|--------------------|
| 1 | 0:00–0:45 | Group and system introduction | Members and their roles (A/B/C). The system has 5 roles, uses Flask + PostgreSQL in Docker, and enforces authorization on the server at three layers: endpoint, record and database. Show the DFD (report Figure 1). |
| 2 | 0:45–1:45 | Authentication demonstration | Log in as `student01` with a wrong password and show the generic message. Log in as `disabled01` and show that it is rejected. Log in correctly as `student01`. Open DevTools → Application → Cookies to show HttpOnly and SameSite=Strict. Log out, then press Back or reload and show that the session is gone (401). |
| 3 | 1:45–2:30 | One authorized operation | Log in as `lecturer01` → Courses → IS101 Roster → set a grade for S2026002 and show "Grade saved". |
| 4 | 2:30–4:30 | Three unauthorized operations | (a) **IDOR:** as `student01`, open `/students/1/grades` and change it to `/students/2/grades` → 403. (b) **Unassigned course:** as `lecturer01`, open `/courses/3/roster` (NW301) → 403. Run test T11 to show that a grade POST to NW301 is rejected and the grade is unchanged. (c) **Administrator without academic role:** as `admin01`, open `/students/1/grades` → 403. Optional: try to assign REGISTRAR to yourself → 403. |
| 5 | 4:30–5:15 | SQL injection / input validation | On the login page enter `' OR '1'='1' --` as username and password → generic failure, no DB error. As `student01`, save address `<script>alert('xss')</script>` and show that it is displayed as text. |
| 6 | 5:15–6:30 | Audit-log inspection | Log in as `auditor01` → Audit log. Filter on result DENIED and point out RECORD_ACCESS_DENIED, GRADE_MODIFY_DENIED and ACCESS_DENIED entries with timestamp, actor, target and result. Click "Verify integrity". In a terminal, run `docker compose exec db psql -U uni_dba -d uni_records -c "DELETE FROM audit_logs WHERE id=1"` and show "append-only". |
| 7 | 6:30–7:00 | Automated tests | Run `python -m pytest tests -q` (pre-recorded, about 2 min) and show `evidence/test-results.html`. |
| 8 | 7:00–8:00 | Contribution statements | Each member speaks for about 20 seconds: what they did, one decision and one problem they solved. |

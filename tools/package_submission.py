"""Create the submission archive ClassID_GroupID_StudentID.zip.

The project folder already follows the layout required by the assignment:

    ClassID_GroupID_StudentID/
    ├── README.md
    ├── report/report.pdf
    ├── source/
    ├── database/  (schema.sql, seed-data.sql)
    ├── tests/
    ├── evidence/
    ├── contribution/  (member-a.pdf, member-b.pdf, member-c.pdf)
    └── demo-video-link.txt

(plus docker-compose.yml, .env.example and docs/, which are needed to run and
rebuild the project). This script checks that every required item exists and
zips the folder under the required name. Secrets (.env), the git repository and
caches are never included.

Usage (from the project folder):
    python tools/package_submission.py --student-id 523H0040
Class and group ids are read from docs/group.json (or --class-id / --group-id).
"""
import argparse
import json
import pathlib
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
REQUIRED = ["README.md", "report/report.pdf", "source", "database/schema.sql", "database/seed-data.sql",
            "database/init/00-create-roles.sql", "docker-compose.yml", ".env.example", "tests",
            "evidence", "contribution/member-a.pdf", "contribution/member-b.pdf", "contribution/member-c.pdf",
            "demo-video-link.txt"]
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "dist", "build", "results", ".venv", "venv", "template"}
SKIP_FILES = {".env"}


def included(path):
    rel = path.relative_to(ROOT)
    if any(part in SKIP_DIRS for part in rel.parts[:-1]) or rel.name in SKIP_FILES:
        return False
    return not rel.name.endswith(".pyc") and rel.parts[0] != "dist"


def main():
    group = json.loads((ROOT / "docs" / "group.json").read_text(encoding="utf-8"))
    ap = argparse.ArgumentParser()
    ap.add_argument("--class-id", default=group.get("class_id"))
    ap.add_argument("--group-id", default=group.get("group_id"))
    ap.add_argument("--student-id", required=True, help="student id of the submitting member")
    args = ap.parse_args()
    for value, label in ((args.class_id, "class id"), (args.group_id, "group id")):
        if not value or value.startswith("<"):
            raise SystemExit(f"Set the {label} in docs/group.json or pass it on the command line.")

    missing = [item for item in REQUIRED if not (ROOT / item).exists()]
    if missing:
        raise SystemExit(f"Missing required items: {missing}")
    link = (ROOT / "demo-video-link.txt").read_text(encoding="utf-8")
    if "<paste" in link:
        print("WARNING: demo-video-link.txt still contains the placeholder - paste the video link first.")

    name = f"{args.class_id}_{args.group_id}_{args.student_id}"
    out = ROOT / "dist" / f"{name}.zip"
    out.parent.mkdir(exist_ok=True)
    files = sorted(p for p in ROOT.rglob("*") if p.is_file() and included(p))
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            zf.write(p, f"{name}/{p.relative_to(ROOT).as_posix()}")
    print(f"{len(files)} files -> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

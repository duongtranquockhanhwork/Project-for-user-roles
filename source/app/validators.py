"""Server-side input validation (allow-list rules).

Validation rejects malformed input with HTTP 400 before it reaches business
logic. It is a complement to, not a replacement for, parameterized queries
(SQL injection) and output encoding (XSS).
"""
import re
from datetime import date
from decimal import Decimal, InvalidOperation

USERNAME_RE = re.compile(r"^[a-z0-9_.]{3,32}$")
STUDENT_CODE_RE = re.compile(r"^[A-Z0-9]{5,12}$")
COURSE_CODE_RE = re.compile(r"^[A-Z]{2,4}[0-9]{3,4}$")
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{1,190}\.[A-Za-z]{2,24}$")
PHONE_RE = re.compile(r"^\+?[0-9][0-9 \-]{6,18}$")
SCORE_RE = re.compile(r"^\d{1,2}(\.\d{1,2})?$")
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

ROLE_NAMES = ("STUDENT", "LECTURER", "REGISTRAR", "AUDITOR", "ADMIN")


class ValidationError(Exception):
    def __init__(self, errors):
        super().__init__("; ".join(errors))
        self.errors = errors


class Validator:
    """Collects all errors of a form so the user sees them together."""

    def __init__(self, form):
        self.form = form
        self.errors = []
        self.data = {}

    def _raw(self, name):
        value = self.form.get(name, "")
        return value.strip() if isinstance(value, str) else ""

    def text(self, name, label, max_len, required=True, min_len=1):
        value = self._raw(name)
        if not value:
            if required:
                self.errors.append(f"{label} is required.")
            self.data[name] = None
            return
        if len(value) < min_len or len(value) > max_len:
            self.errors.append(f"{label} must be {min_len}-{max_len} characters.")
        elif _CONTROL_CHARS.search(value):
            self.errors.append(f"{label} contains invalid characters.")
        self.data[name] = value

    def pattern(self, name, label, regex, required=True, transform=None):
        value = self._raw(name)
        if transform:
            value = transform(value)
        if not value:
            if required:
                self.errors.append(f"{label} is required.")
            self.data[name] = None
            return
        if not regex.fullmatch(value):
            self.errors.append(f"{label} has an invalid format.")
        self.data[name] = value

    def date(self, name, label, required=False):
        value = self._raw(name)
        if not value:
            if required:
                self.errors.append(f"{label} is required.")
            self.data[name] = None
            return
        try:
            parsed = date.fromisoformat(value)
            if not date(1900, 1, 1) <= parsed <= date.today():
                raise ValueError
            self.data[name] = parsed
        except ValueError:
            self.errors.append(f"{label} must be a valid date (YYYY-MM-DD).")

    def positive_int(self, name, label):
        value = self._raw(name)
        if not value.isdigit() or len(value) > 9 or int(value) == 0:
            self.errors.append(f"{label} is invalid.")
            self.data[name] = None
        else:
            self.data[name] = int(value)

    def score(self, name="score"):
        value = self._raw(name)
        if not SCORE_RE.fullmatch(value):
            self.errors.append("Score must be a number between 0 and 10 with at most 2 decimals.")
            self.data[name] = None
            return
        try:
            score = Decimal(value)
        except InvalidOperation:
            score = None
        if score is None or not Decimal("0") <= score <= Decimal("10"):
            self.errors.append("Score must be a number between 0 and 10 with at most 2 decimals.")
            self.data[name] = None
        else:
            self.data[name] = score

    def choice(self, name, label, choices):
        value = self._raw(name)
        if value not in choices:
            self.errors.append(f"{label} is invalid.")
            self.data[name] = None
        else:
            self.data[name] = value

    def password(self, name, label, min_len):
        value = self.form.get(name, "")
        if not isinstance(value, str) or not min_len <= len(value) <= 128:
            self.errors.append(f"{label} must be {min_len}-128 characters.")
        elif _CONTROL_CHARS.search(value):
            self.errors.append(f"{label} contains invalid characters.")
        self.data[name] = value

    def done(self):
        if self.errors:
            raise ValidationError(self.errors)
        return self.data


def contact_fields(v):
    v.pattern("email", "Email", EMAIL_RE, required=False)
    v.pattern("phone", "Phone", PHONE_RE, required=False)
    v.text("address", "Address", 200, required=False)

"""Security audit logging.

Entries are written to the append-only `audit_logs` table. The database
trigger assigns the id, timestamp and hash-chain values, and blocks any UPDATE,
DELETE or TRUNCATE.

Secrets (passwords, session tokens, CSRF tokens, database credentials) are
never written: sensitive keys are removed from `details` before insertion.
"""
import json

from flask import g, has_request_context, request

from . import db

SUCCESS = "SUCCESS"
DENIED = "DENIED"
FAILURE = "FAILURE"

_SENSITIVE_KEYS = {"password", "new_password", "password_hash", "token", "session",
                   "session_token", "csrf_token", "cookie", "secret", "db_password"}
_MAX_VALUE_LEN = 200


def _clean(details):
    clean = {}
    for key, value in (details or {}).items():
        if key.lower() in _SENSITIVE_KEYS:
            continue
        if isinstance(value, str):
            value = value[:_MAX_VALUE_LEN]
        elif not isinstance(value, (int, float, bool, type(None), list)):
            value = str(value)[:_MAX_VALUE_LEN]
        clean[key] = value
    return clean


def log_event(event_type, result, target=None, details=None, *, actor_id=None,
              actor_username=None, in_request_tx=False):
    """Write one audit entry.

    in_request_tx=True  -> the entry is part of the request's transaction, so
                           it is committed atomically with the data change it
                           describes (e.g. a grade update).
    in_request_tx=False -> the entry is committed immediately in a separate
                           transaction (e.g. a rejected request that changes
                           nothing).
    """
    user = g.get("user") if has_request_context() else None
    if actor_id is None and user is not None:
        actor_id = user.id
    if actor_username is None and user is not None:
        actor_username = user.username
    source_ip = request.remote_addr if has_request_context() else None

    sql = ("INSERT INTO audit_logs (actor_user_id, actor_username, event_type, "
           "target_resource, result, details, source_ip) "
           "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)")
    params = (actor_id, actor_username, event_type, target, result,
              json.dumps(_clean(details), ensure_ascii=False), source_ip)

    if in_request_tx:
        db.execute(sql, params)
    else:
        with db.separate_transaction() as conn:
            db.execute(sql, params, conn=conn)

"""Idempotency keys for money-creating API posts (FR-35).

The key is reserved in its own transaction before the use case runs, so a concurrent duplicate sees
the reservation and is refused instead of running twice. The first successful response is stored and
replayed for 24 hours; a different request under the same key is a conflict. If the use case fails,
the reservation is removed so the client can retry.

Deviation from the plan: the use cases open their own transactions (they are shared with the HTML
pages), so the stored response is written just after the effect commits, not in the same transaction.
A crash between the two leaves the key reserved until it expires, which refuses a retry rather than
duplicating money.
"""

import hashlib
import json
import sqlite3
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from app.api.v1.problems import problem
from app.db.unit_of_work import transaction
from app.shared.clock import Clock, to_utc_text

TTL = timedelta(hours=24)
IN_PROGRESS = 0


def _valid(key: str) -> bool:
    return 1 <= len(key) <= 64 and all(0x21 <= ord(ch) <= 0x7E for ch in key)


def _request_hash(request: Request, payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(f"{request.method} {request.url.path}\n{canonical}".encode()).hexdigest()


def run(conn: sqlite3.Connection, request: Request, *, user_id: int, payload: Any, clock: Clock,
        produce: Callable[[], tuple[int, Any]]) -> Response:
    """Run ``produce`` (which returns a status code and a JSON body) at most once per key."""
    key = request.headers.get("idempotency-key")
    if key is None:
        status, body = produce()
        return JSONResponse(body, status_code=status)
    if not _valid(key):
        return problem(400, "Invalid Idempotency-Key", "Use 1 to 64 visible ASCII characters.")
    digest = _request_hash(request, payload)
    now = clock.now_utc()
    with transaction(conn):
        conn.execute("DELETE FROM idempotency_keys WHERE created_at < ?", (to_utc_text(now - TTL),))
        row = conn.execute("SELECT request_hash, status_code, response_json FROM idempotency_keys"
                           " WHERE user_id = ? AND key = ?", (user_id, key)).fetchone()
        if row is None:
            conn.execute("INSERT INTO idempotency_keys (user_id, key, request_hash, status_code, response_json,"
                         " created_at) VALUES (?, ?, ?, ?, '{}', ?)",
                         (user_id, key, digest, IN_PROGRESS, to_utc_text(now)))
    if row is not None:
        if row["request_hash"] != digest:
            return problem(409, "Idempotency-Key reused", "That key was already used for a different request.")
        if row["status_code"] == IN_PROGRESS:
            return problem(409, "Request in progress", "A request with that key is still being processed.")
        return JSONResponse(json.loads(row["response_json"]), status_code=row["status_code"],
                            headers={"Idempotent-Replayed": "true"})
    try:
        status, body = produce()
    except BaseException:
        with transaction(conn):
            conn.execute("DELETE FROM idempotency_keys WHERE user_id = ? AND key = ?", (user_id, key))
        raise
    with transaction(conn):
        conn.execute("UPDATE idempotency_keys SET status_code = ?, response_json = ? WHERE user_id = ? AND key = ?",
                     (status, json.dumps(body), user_id, key))
    return JSONResponse(body, status_code=status)

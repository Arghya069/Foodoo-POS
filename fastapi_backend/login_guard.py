"""Firestore-backed short-window login throttling.

Rate limit identity is scoped to username and network peer; the peer IP may be
an ingress proxy on Cloud Run. Enforce Cloud Armor limits at the load balancer
for additional network-level protection.
"""
import hashlib
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from google.cloud import firestore

ATTEMPTS = 8
WINDOW = timedelta(minutes=5)


def attempt_key(username, peer):
    raw = (username.strip().casefold() + "\x00" + (peer or "unknown")).encode()
    return hashlib.sha256(raw).hexdigest()


def check_login_attempt(db, username, peer):
    ref = db.collection("login_attempts").document(attempt_key(username, peer))
    snap = ref.get()
    if not snap.exists:
        return
    value = snap.to_dict()
    now = datetime.now(timezone.utc)
    if (value.get("expires_at") and now < value["expires_at"]
            and value.get("failures", 0) >= ATTEMPTS):
        raise HTTPException(429, "Too many login attempts. Try again in a few minutes.")


def record_login_failure(db, username, peer):
    ref = db.collection("login_attempts").document(attempt_key(username, peer))
    tx = db.transaction()

    @firestore.transactional
    def record(transaction):
        snap = ref.get(transaction=transaction)
        old = snap.to_dict() if snap.exists else {}
        now = datetime.now(timezone.utc)
        if old.get("expires_at") and old["expires_at"] > now:
            count = int(old.get("failures", 0)) + 1
            expiry = old["expires_at"]
        else:
            count, expiry = 1, now + WINDOW
        transaction.set(ref, {"failures": min(count, ATTEMPTS),
                              "expires_at": expiry}, merge=True)
    record(tx)


def clear_login_failures(db, username, peer):
    # Best effort; never change authentication success into a failure because
    # the housekeeping deletion failed.
    try:
        db.collection("login_attempts").document(attempt_key(username, peer)).delete()
    except Exception:
        pass

"""Firestore-backed revocable sessions with absolute and idle expiry."""
import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

COLLECTION = "sessions"
ABSOLUTE_HOURS = 8
IDLE_MINUTES = 60
TOUCH_MINUTES = 5


def utcnow():
    return datetime.now(timezone.utc)


def document_id(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_session(db, user_id, restaurant_id):
    token = secrets.token_urlsafe(48)
    created = utcnow()
    reference = db.collection(COLLECTION).document(document_id(token))
    reference.create({
        "user_id": user_id,
        "restaurant_id": restaurant_id,
        "created_at": created,
        "last_seen_at": created,
        "expires_at": created + timedelta(hours=ABSOLUTE_HOURS),
        "revoked": False,
    })
    return token


def validate_session(db, token):
    if not token:
        return None
    reference = db.collection(COLLECTION).document(document_id(token))
    snap = reference.get()
    if not snap.exists:
        return None
    data = snap.to_dict()
    current = utcnow()
    last_seen = data.get("last_seen_at") or data.get("created_at")
    if (data.get("revoked") or not last_seen or
            data["expires_at"] <= current or
            last_seen + timedelta(minutes=IDLE_MINUTES) <= current):
        return None
    # Reduce Firestore writes; a busy session writes at most once per 5 minutes.
    if current - last_seen >= timedelta(minutes=TOUCH_MINUTES):
        reference.update({"last_seen_at": current})
    return {"id": snap.id, **data}


def revoke_session(db, token):
    if token:
        db.collection(COLLECTION).document(document_id(token)).update({"revoked": True})


def revoke_user_sessions(db, user_id):
    for snap in db.collection(COLLECTION).where("user_id", "==", user_id).stream():
        if not snap.to_dict().get("revoked"):
            snap.reference.update({"revoked": True})


def user_sessions(db, user_id):
    current = utcnow()
    result = []
    for snap in db.collection(COLLECTION).where("user_id", "==", user_id).stream():
        data = snap.to_dict()
        if data.get("revoked") or data.get("expires_at", current) <= current:
            continue
        result.append({
            "id": snap.id,
            "created_at": data["created_at"],
            "last_seen_at": data["last_seen_at"],
            "expires_at": data["expires_at"],
        })
    return result

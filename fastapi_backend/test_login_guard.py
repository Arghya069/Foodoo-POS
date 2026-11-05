"""Login attempt throttling behavior without Firestore access."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from login_guard import ATTEMPTS, attempt_key, check_login_attempt


class FakeDocument:
    def __init__(self,data):
        self.data=data

    def get(self):
        return SimpleNamespace(exists=bool(self.data),
                               to_dict=lambda:self.data)


class FakeCollection:
    def __init__(self,data):
        self.data=data

    def document(self,id):
        return FakeDocument(self.data)


class FakeDB:
    def __init__(self,data):
        self.data=data

    def collection(self,name):
        assert name=="login_attempts"
        return FakeCollection(self.data)


def test_login_attempt_identifier_is_hashed_and_normalizes_username():
    assert attempt_key(" Cashier ","198.51.100.1")==attempt_key("cashier","198.51.100.1")
    assert attempt_key("cashier","198.51.100.2")!=attempt_key("cashier","198.51.100.1")
    assert "cashier" not in attempt_key("cashier","198.51.100.1")


def test_login_blocked_after_many_recent_failures():
    db=FakeDB({"failures":ATTEMPTS,"expires_at":datetime.now(timezone.utc)+timedelta(minutes=5)})
    with pytest.raises(HTTPException) as error:
        check_login_attempt(db,"cashier","198.51.100.1")
    assert error.value.status_code==429


def test_old_login_failures_expire():
    db=FakeDB({"failures":ATTEMPTS,"expires_at":datetime.now(timezone.utc)-timedelta(seconds=1)})
    check_login_attempt(db,"cashier","198.51.100.1")

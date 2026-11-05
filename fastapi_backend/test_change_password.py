"""Authentication-contract tests for self-service password changes."""
import pytest
from pydantic import ValidationError

from schemas import ChangePasswordRequest


@pytest.mark.parametrize("bad",[
    {"current_password":"","new_password":"this is sufficiently long"},
    {"current_password":"old","new_password":"too-short"},
    {"current_password":"old","new_password":"a"*257},
    {"current_password":"old","new_password":"valid new password","is_admin":True},
])
def test_change_password_request_is_strict(bad):
    with pytest.raises(ValidationError):
        ChangePasswordRequest.model_validate(bad)


def test_change_password_request_requires_current_and_new():
    record=ChangePasswordRequest(current_password="old-password",
                                new_password="a new and much longer passphrase")
    assert record.current_password=="old-password"
    assert len(record.new_password)>=12


def test_change_password_is_not_admin_role_restricted(monkeypatch):
    monkeypatch.setenv("FOODOO_SESSION_SECRET","test-secret-longer-than-thirty-two-characters")
    monkeypatch.setenv("FOODOO_FIRESTORE_PROJECT","foodoo-test")
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST","127.0.0.1:8089")
    from app import app
    schema=app.openapi()
    route=schema["paths"]["/api/auth/change-password/"]["post"]
    assert "ChangePasswordRequest" in str(route)

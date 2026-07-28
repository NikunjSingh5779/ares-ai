"""Tests for password hashing and JWT token creation.

The bcrypt backend has known compatibility issues with passlib on Python 3.14+,
so we mock the password context in those tests.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from backend.core.security import create_access_token


class TestPasswordHashing:
    """hash_password and verify_password with mocked passlib context."""

    @patch("backend.core.security.pwd_context")
    def test_hash_password(self, mock_pwd_context):
        mock_pwd_context.hash.return_value = "$2b$12$hashedpassword"
        from backend.core.security import hash_password

        result = hash_password("my_secret_pass")
        assert result == "$2b$12$hashedpassword"
        mock_pwd_context.hash.assert_called_once_with("my_secret_pass")

    @patch("backend.core.security.pwd_context")
    def test_verify_password_correct(self, mock_pwd_context):
        mock_pwd_context.verify.return_value = True
        from backend.core.security import verify_password

        result = verify_password("my_secret_pass", "$2b$12$hashedpassword")
        assert result is True
        mock_pwd_context.verify.assert_called_once_with("my_secret_pass", "$2b$12$hashedpassword")

    @patch("backend.core.security.pwd_context")
    def test_verify_password_wrong(self, mock_pwd_context):
        mock_pwd_context.verify.return_value = False
        from backend.core.security import verify_password

        result = verify_password("wrong_password", "$2b$12$hashedpassword")
        assert result is False


class TestCreateAccessToken:
    """create_access_token coverage."""

    def test_create_token_without_expires_delta(self) -> None:
        token = create_access_token({"sub": "test_user"})
        assert isinstance(token, str)
        assert len(token) > 20

    def test_create_token_with_expires_delta(self) -> None:
        token = create_access_token({"sub": "test_user"}, expires_delta=timedelta(minutes=5))
        assert isinstance(token, str)
        assert len(token) > 20

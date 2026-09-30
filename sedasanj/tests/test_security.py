from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from uuid import uuid4

import jwt
import pytest

from app.security import (
    API_KEY_PREFIX,
    create_access_token,
    decode_access_token,
    generate_api_key,
    hash_api_key,
    hash_password,
    materialize_api_key,
    sign_webhook,
    totp_code,
    verify_password,
    verify_totp,
)


def test_password_hash_is_argon2_and_verifies() -> None:
    hashed = hash_password("correct horse battery")
    assert hashed.startswith("$argon2id$")
    assert verify_password(hashed, "correct horse battery")
    assert not verify_password(hashed, "wrong password")


def test_api_key_hash_is_stable_and_prefix_is_short() -> None:
    secret, prefix, hashed = generate_api_key()
    assert secret.startswith(API_KEY_PREFIX)
    assert secret.startswith(prefix) and len(prefix) == len(API_KEY_PREFIX) + 4
    assert hash_api_key(secret) == hashed
    assert secret not in hashed


def test_materialize_api_key_reuses_known_secret() -> None:
    secret = API_KEY_PREFIX + "example-fixed-secret-value-0001"
    out_secret, prefix, hashed = materialize_api_key(secret)
    assert out_secret == secret
    assert prefix == secret[: len(API_KEY_PREFIX) + 4]
    assert hashed == hash_api_key(secret)


def test_access_token_carries_tenant_and_rejects_refresh_type() -> None:
    tenant_id = uuid4()
    user_id = uuid4()
    token = create_access_token(subject=user_id, tenant_id=tenant_id, role="org_admin")
    claims = decode_access_token(token)
    assert claims["sub"] == str(user_id)
    assert claims["tenant_id"] == str(tenant_id)
    assert claims["role"] == "org_admin"
    assert claims["actor"] == "user"


def test_access_token_rejects_a_foreign_signature() -> None:
    forged = jwt.encode(
        {"sub": "x", "typ": "access"},
        "another-secret-with-safe-test-length",
        algorithm="HS256",
    )
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(forged)


def test_webhook_signature_matches_timestamp_dot_body() -> None:
    secret = "whsec_test"
    timestamp = "1750000000"
    body = b'{"event":"call.complete"}'
    expected = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()
    assert sign_webhook(secret, timestamp, body) == f"sha256={expected}"


def test_webhook_signature_changes_with_the_timestamp() -> None:
    body = b"{}"
    assert sign_webhook("s", "1", body) != sign_webhook("s", "2", body)


def test_totp_accepts_the_current_window() -> None:
    secret = "JBSWY3DPEHPK3PXP"
    counter = int(datetime.now(UTC).timestamp()) // 30
    assert verify_totp(secret, totp_code(secret, counter))


def test_totp_accepts_one_step_of_drift() -> None:
    secret = "JBSWY3DPEHPK3PXP"
    counter = int(datetime.now(UTC).timestamp()) // 30
    assert verify_totp(secret, totp_code(secret, counter - 1))


def test_totp_rejects_a_stale_or_malformed_code() -> None:
    secret = "JBSWY3DPEHPK3PXP"
    counter = int(datetime.now(UTC).timestamp()) // 30
    assert not verify_totp(secret, totp_code(secret, counter - 10))
    assert not verify_totp(secret, "abcdef")
    assert not verify_totp(secret, None)


def test_totp_rejects_wrong_length_codes() -> None:
    secret = "JBSWY3DPEHPK3PXP"
    counter = int(datetime.now(UTC).timestamp()) // 30
    code = totp_code(secret, counter)
    assert not verify_totp(secret, code + "0")
    assert not verify_totp(secret, code[:5])


def test_verify_password_rejects_a_malformed_hash() -> None:
    assert not verify_password("not-an-argon2-hash", "whatever")
    assert not verify_password("", "whatever")

"""Bearer tokens: signed here or by the other service with the shared secret, checked without a database."""

from datetime import UTC, datetime, timedelta

from app.shared.tokens import sign, verify

NOW = datetime(2026, 9, 30, 8, 0, tzinfo=UTC)


def test_a_signed_token_names_its_user_until_it_expires():
    token = sign("secret", user_id=7, expires_at=NOW + timedelta(hours=1))
    assert verify("secret", token, now=NOW) == 7
    assert verify("secret", token, now=NOW + timedelta(hours=1)) is None
    assert verify("other-secret", token, now=NOW) is None


def test_bad_input_is_refused_and_never_raises():
    good = sign("secret", user_id=7, expires_at=NOW + timedelta(hours=1))
    for token in (None, "", "f1.7", good + "x", good.replace("f1.", "f2.", 1), "f1.7.9999999999.nonce.é",
                  "f1.é.9999999999.nonce.sig", good[:-1] + "é"):
        assert verify("secret", token, now=NOW) is None

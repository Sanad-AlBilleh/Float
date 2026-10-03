"""CSRF, cookies, headers, error pages, and request logging (FR-04, SRS §9, NFR-10)."""

import json
import logging

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.web.helpers import ORIGIN, PASSWORD, csrf_from, sign_up


def test_posts_without_a_csrf_token_are_rejected(client):
    sign_up(client)
    response = client.post("/logout", data={}, follow_redirects=False)
    assert response.status_code == 403
    assert client.get("/account", follow_redirects=False).status_code == 200  # still signed in


def test_posts_from_another_site_are_rejected_even_with_a_token(client):
    sign_up(client)
    token = csrf_from(client.get("/account"))
    response = client.post(
        "/logout", data={"csrf_token": token}, headers={"Origin": "https://evil.example"}, follow_redirects=False
    )
    assert response.status_code == 403


def test_same_origin_posts_are_accepted(client):
    sign_up(client)
    token = csrf_from(client.get("/account"))
    response = client.post(
        "/logout", data={"csrf_token": token}, headers={"Origin": "http://testserver"}, follow_redirects=False
    )
    assert response.status_code == 303


def test_anonymous_forms_use_a_double_submit_cookie(client):
    page = client.get("/register")
    assert csrf_from(page) == client.cookies.get("float_csrf")
    forged = client.post(
        "/register",
        data={"username": "ana", "display_name": "Ana", "password": PASSWORD, "csrf_token": "forged"},
        follow_redirects=False,
    )
    assert forged.status_code == 403


def test_every_response_has_security_headers_and_a_request_id(client):
    for path in ("/", "/login", "/healthz", "/static/float.css", "/no-such-page"):
        response = client.get(path)
        assert response.headers["content-security-policy"].startswith("default-src 'self'"), path
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["referrer-policy"] == "same-origin"
        assert len(response.headers["x-request-id"]) == 32


def test_api_docs_are_exempt_from_the_content_security_policy(client):
    response = client.get("/api/docs")
    assert response.status_code == 200
    assert "content-security-policy" not in response.headers


def test_session_cookie_is_http_only_and_same_site(client):
    cookie = sign_up(client).headers["set-cookie"].lower()
    assert "float_session=" in cookie and "httponly" in cookie and "samesite=lax" in cookie
    assert "secure" not in cookie


def test_session_cookie_is_secure_when_configured(tmp_path, clock):
    app = create_app(Settings(data_dir=tmp_path / "data", cookie_secure=True), clock)
    with TestClient(app, base_url="https://testserver") as browser:
        assert "secure" in sign_up(browser).headers["set-cookie"].lower()


def test_unexpected_errors_show_a_request_id_but_no_internals(app):
    def explode():
        raise RuntimeError("secret internals")

    app.add_api_route("/explode", explode)
    with TestClient(app) as browser:
        response = browser.get("/explode")
    assert response.status_code == 500
    assert "secret internals" not in response.text
    assert response.headers["x-request-id"] in response.text


def test_unknown_pages_render_the_not_found_page(client):
    response = client.get("/no-such-page")
    assert response.status_code == 404
    assert "Not found" in response.text


def test_request_log_uses_route_templates_and_no_secrets(client, caplog):
    sign_up(client)
    session_cookie = client.cookies.get("float_session")
    with caplog.at_level(logging.INFO, logger="float.request"):
        client.get("/account")
    records = [record for record in caplog.records if record.name == "float.request"]
    line = json.loads(records[-1].getMessage())
    assert line["route"] == "/account" and line["status"] == 200 and line["user_id"] is not None
    assert set(line) == {"request_id", "method", "route", "status", "duration_ms", "user_id"}
    assert all(session_cookie not in record.getMessage() for record in caplog.records)


def test_form_posts_need_a_same_site_origin_or_referer(client):
    sign_up(client)
    token = csrf_from(client.get("/account"))
    bare = client.post("/logout", data={"csrf_token": token}, follow_redirects=False)
    assert bare.status_code == 403
    with_referer = client.post("/logout", data={"csrf_token": token},
                               headers={"Referer": "http://testserver/account"}, follow_redirects=False)
    assert with_referer.status_code == 303


def test_header_tokens_from_scripts_do_not_need_an_origin(client):
    sign_up(client)
    token = csrf_from(client.get("/account"))
    response = client.post("/logout", headers={"X-CSRF-Token": token}, follow_redirects=False)
    assert response.status_code == 303


def test_oversized_forms_are_refused(client):
    sign_up(client)
    token = csrf_from(client.get("/account"))
    response = client.post("/account/password", data={"csrf_token": token, "current_password": "x" * 70_000},
                           headers=ORIGIN, follow_redirects=False)
    assert response.status_code == 413
    assert "too large" in response.text
    assert "x" * 1000 not in response.text


def test_error_pages_keep_the_signed_in_navigation(app):
    def explode():
        raise RuntimeError("boom")

    app.add_api_route("/explode", explode)
    with TestClient(app) as browser:
        sign_up(browser)
        for path, status in (("/nope", 404), ("/logout", 405), ("/explode", 500)):
            response = browser.get(path)
            assert response.status_code == status, path
            assert "Log out" in response.text and "Create account" not in response.text, path


def test_checkboxes_and_radios_are_not_stretched_like_text_inputs(client):
    css = client.get("/static/float.css").text
    rule = css[css.index('.field input[type="checkbox"]'):]
    assert "width: auto" in rule[:rule.index("}")]

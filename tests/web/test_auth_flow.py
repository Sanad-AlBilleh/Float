"""Registration, login, logout, and password changes through the browser (FR-01–03, AT-01, AT-02)."""

from tests.web.helpers import PASSWORD, log_in, log_out, post_form, sign_up

NEW_PASSWORD = "a brand new passphrase"


def test_registration_signs_the_new_user_in(client):
    response = sign_up(client)
    assert response.headers["location"] == "/"
    page = client.get("/account")
    assert page.status_code == 200 and "Ana" in page.text


def test_a_taken_username_is_explained_and_values_are_kept(client, make_client):
    sign_up(client)
    other = make_client()
    response = post_form(
        other, "/register", "/register", {"username": "ANA", "display_name": "Second", "password": PASSWORD}
    )
    assert response.status_code == 400
    assert "That username is taken." in response.text
    assert 'value="ANA"' in response.text and 'value="Second"' in response.text
    assert PASSWORD not in response.text


def test_wrong_password_and_unknown_user_get_the_same_message(client):
    sign_up(client)
    log_out(client)
    wrong = log_in(client, password="definitely wrong")
    unknown = log_in(client, username="nobody", password="definitely wrong")
    assert wrong.status_code == unknown.status_code == 400
    assert "Incorrect username or password." in wrong.text
    assert "Incorrect username or password." in unknown.text


def test_five_failures_show_the_lockout_message(client):
    sign_up(client)
    log_out(client)
    for _ in range(5):
        log_in(client, password="definitely wrong")
    response = log_in(client)
    assert response.status_code == 400
    assert "Too many attempts. Try again in 15 minutes." in response.text


def test_login_only_redirects_to_local_paths(client):
    sign_up(client)
    log_out(client)
    assert log_in(client, next_path="/account").headers["location"] == "/account"
    log_out(client)
    assert log_in(client, next_path="https://evil.example/").headers["location"] == "/"
    for sneaky in ("//evil.example/x", "/\\evil.example", "/\t/evil.example", "/\n/evil.example"):
        log_out(client)
        assert log_in(client, next_path=sneaky).headers["location"] == "/", sneaky


def test_anonymous_visitors_are_sent_to_login_with_a_return_path(client):
    response = client.get("/account", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=/account"


def test_logout_ends_the_session(client):
    sign_up(client)
    response = log_out(client)
    assert response.status_code == 303
    assert "max-age=0" in response.headers["set-cookie"].lower()
    assert client.cookies.get("float_session") is None
    assert client.get("/account", follow_redirects=False).status_code == 303


def test_changing_the_password(client):
    sign_up(client)
    wrong = post_form(client, "/account", "/account/password",
                      {"current_password": "not my password", "new_password": NEW_PASSWORD})
    assert wrong.status_code == 400 and "That is not your current password." in wrong.text
    done = post_form(client, "/account", "/account/password",
                     {"current_password": PASSWORD, "new_password": NEW_PASSWORD})
    assert done.status_code == 303 and done.headers["location"] == "/account?changed=1"
    assert "Password changed." in client.get("/account?changed=1").text
    log_out(client)
    assert log_in(client, password=NEW_PASSWORD).status_code == 303


def test_changing_the_password_signs_out_other_browsers(client, make_client):
    sign_up(client)
    laptop = make_client()
    assert log_in(laptop).status_code == 303
    post_form(client, "/account", "/account/password", {"current_password": PASSWORD, "new_password": NEW_PASSWORD})
    assert laptop.get("/account", follow_redirects=False).status_code == 303
    assert client.get("/account").status_code == 200

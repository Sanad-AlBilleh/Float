"""Browser-style helpers: every form post carries the CSRF token from the page that shows the form."""

import re

CSRF_INPUT = re.compile(r'name="csrf_token" value="([^"]*)"')
PASSWORD = "correct horse battery"


def csrf_from(response) -> str:
    match = CSRF_INPUT.search(response.text)
    assert match, f"no CSRF field on {response.url}"
    return match.group(1)


def post_form(client, page_url: str, action_url: str, data: dict, **kwargs):
    token = csrf_from(client.get(page_url))
    return client.post(action_url, data={**data, "csrf_token": token}, follow_redirects=False, **kwargs)


def sign_up(client, username: str = "ana", display_name: str = "Ana", password: str = PASSWORD):
    response = post_form(
        client, "/register", "/register",
        {"username": username, "display_name": display_name, "password": password},
    )
    assert response.status_code == 303, response.text
    return response


def log_in(client, username: str = "ana", password: str = PASSWORD, next_path: str = "/"):
    return post_form(client, "/login", "/login", {"username": username, "password": password, "next": next_path})


def log_out(client):
    return post_form(client, "/account", "/logout", {})

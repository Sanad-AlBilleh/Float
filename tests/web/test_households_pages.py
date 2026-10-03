"""Household pages: create, invite, join, leave, and owner actions (FR-17–19)."""

import re

from tests.web.helpers import ORIGIN, csrf_from, post_form, set_up, sign_up

CODE = re.compile(r'<code class="invite-code">([0-9A-Z]{10})</code>')


def person(make_client, username):
    browser = make_client()
    sign_up(browser, username, username.title())
    set_up(browser)
    return browser


def create(client, name="Flat 3B"):
    response = post_form(client, "/households", "/households/new", {"name": name})
    assert response.status_code == 303, response.text
    return response.headers["location"].split("?")[0]


def invite(client, page):
    response = post_form(client, page + "?tab=members", page + "/invitations", {})
    assert response.status_code == 200
    return CODE.search(response.text).group(1)


def join(client, code):
    return post_form(client, "/households", "/households/join", {"code": code})


def test_create_invite_and_join(client, make_client):
    sign_up(client)
    set_up(client)
    page = create(client)
    assert re.fullmatch(r"/households/\d+", page)
    code = invite(client, page)
    assert code not in client.get(page + "?tab=members").text  # shown once only
    ben = person(make_client, "ben")
    assert join(ben, code.lower()).headers["location"] == page
    members = client.get(page + "?tab=members").text
    assert "Ana" in members and "Ben" in members and "Owner" in members
    again = join(person(make_client, "carla"), code)
    assert again.status_code == 400 and "not valid" in again.text


def test_members_cannot_use_owner_actions_and_strangers_see_nothing(client, make_client):
    sign_up(client)
    set_up(client)
    page = create(client)
    ben = person(make_client, "ben")
    join(ben, invite(client, page))
    token = csrf_from(ben.get(page))
    assert ben.post(page + "/invitations", data={"csrf_token": token}, headers=ORIGIN,
                    follow_redirects=False).status_code == 403
    stranger = person(make_client, "eve")
    assert stranger.get(page).status_code == 404
    assert ">Flat 3B</a>" not in stranger.get("/households").text


def test_leaving_keeps_read_access_to_history(client, make_client):
    sign_up(client)
    set_up(client)
    page = create(client)
    ben = person(make_client, "ben")
    join(ben, invite(client, page))
    assert post_form(ben, page, page + "/leave", {}).status_code == 303
    history = ben.get(page)
    assert history.status_code == 200 and "You left this household" in history.text
    assert "Former" in client.get(page + "?tab=members").text


def test_owner_settings(client, make_client):
    sign_up(client)
    set_up(client)
    page = create(client)
    ben = person(make_client, "ben")
    join(ben, invite(client, page))
    version = re.search(r'name="version" value="(\d+)"', client.get(page + "?tab=members").text).group(1)
    assert post_form(client, page + "?tab=members", page + "/rename",
                     {"name": "Flat 3B 2026", "version": version}).status_code == 303
    assert "Flat 3B 2026" in client.get(page).text
    version = re.search(r'name="version" value="(\d+)"', client.get(page + "?tab=members").text).group(1)
    ben_id = re.search(r'name="new_owner" value="(\d+)"|<option value="(\d+)">Ben', client.get(page + "?tab=members").text)
    ben_id = next(group for group in ben_id.groups() if group)
    assert post_form(client, page + "?tab=members", page + "/transfer",
                     {"new_owner": ben_id, "version": version}).status_code == 303
    assert "Owner" in ben.get(page + "?tab=members").text
    blocked = post_form(ben, page + "?tab=members", page + "/archive",
                        {"version": re.search(r'name="version" value="(\d+)"', ben.get(page + "?tab=members").text).group(1)})
    assert blocked.status_code == 303 and "archived" in ben.get(page).text.lower()


def test_an_invalid_name_is_explained(client):
    sign_up(client)
    set_up(client)
    response = post_form(client, "/households", "/households/new", {"name": ""})
    assert response.status_code == 400 and "Enter a name of 1 to 60 characters." in response.text


def test_former_members_and_plain_members_cannot_change_things(client, make_client):
    sign_up(client)
    set_up(client)
    page = create(client)
    ben, carla = person(make_client, "ben"), person(make_client, "carla")
    join(ben, invite(client, page))
    join(carla, invite(client, page))
    carla_id = re.search(r'/members/(\d+)/remove"[^>]*>\s*<input[^>]*>\s*<button[^>]*>Remove<span class="visually-hidden"> Carla',
                         client.get(page + "?tab=members").text)
    carla_id = carla_id.group(1) if carla_id else "3"
    token = csrf_from(ben.get(page))
    removal = ben.post(f"{page}/members/{carla_id}/remove", data={"csrf_token": token}, headers=ORIGIN,
                       follow_redirects=False)
    assert removal.status_code == 403
    post_form(ben, page, page + "/leave", {})
    token = csrf_from(ben.get(page))
    again = ben.post(page + "/leave", data={"csrf_token": token}, headers=ORIGIN, follow_redirects=False)
    assert again.status_code == 404
    invitation = ben.post(page + "/invitations", data={"csrf_token": token}, headers=ORIGIN, follow_redirects=False)
    assert invitation.status_code == 404  # a former member is a stranger for every change

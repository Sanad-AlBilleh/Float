"""The bills pages through the browser (FR-09–13, AT-08, AT-09)."""

import re

from tests.web.helpers import ORIGIN, csrf_from, post_form, set_up, sign_up

ACTION = re.compile(r'action="/bills/occurrences/(\d+)/(pay|undo|skip|unskip)"')


def add_bill(client, **fields):
    data = {"name": "Phone", "amount": "120", "category_id": "4", "freq": "monthly", "interval": "1",
            "anchor_date": "2026-09-25", "until": "", "count": ""}
    data.update(fields)
    return post_form(client, "/bills/new", "/bills/new", data)


def actions(client) -> list[tuple[int, str]]:
    return [(int(number), action) for number, action in ACTION.findall(client.get("/bills").text)]


def version(client, occurrence_id: int) -> str:
    page = client.get(f"/bills/occurrences/{occurrence_id}").text
    return re.search(r'name="version" value="(\d+)"', page).group(1)


def act(client, occurrence_id: int, action: str, **fields):
    data = {"version": version(client, occurrence_id), **fields}
    return post_form(client, "/bills", f"/bills/occurrences/{occurrence_id}/{action}", data)


def ready(client):
    sign_up(client)
    set_up(client, opening_balance="500")
    assert add_bill(client).status_code == 303


def test_a_new_bill_lists_its_occurrences_with_status_text(client):
    ready(client)
    page = client.get("/bills").text
    assert "Phone" in page and "Overdue" in page and "Upcoming" in page
    assert "2026-09-25" in page and "2026-10-25" in page
    assert "Monthly" in page


def test_an_invalid_bill_keeps_its_values_and_lists_every_problem(client):
    sign_up(client)
    set_up(client)
    response = add_bill(client, name="", amount="12,345", anchor_date="2026-08-01", until="2026-12-01", count="3")
    assert response.status_code == 400
    for message in ("Enter a name of 1 to 100 characters.", "Use at most two decimal places.",
                    "when tracking started", "Choose an end date or a number of occurrences, not both."):
        assert message in response.text
    assert 'value="12,345"' in response.text


def test_paying_and_undoing_from_the_bills_page(client):
    ready(client)
    occurrence_id = [number for number, action in actions(client) if action == "pay"][0]
    assert act(client, occurrence_id, "pay", paid_on="2026-09-30").status_code == 303
    assert "Paid" in client.get("/bills").text
    assert "Managed by its bill" in client.get("/transactions").text
    assert "€380.00" in client.get("/").text  # €500 opening − €120 phone
    assert act(client, occurrence_id, "undo").status_code == 303
    assert "Managed by its bill" not in client.get("/transactions").text


def test_paying_twice_changes_nothing(client):
    ready(client)
    occurrence_id = actions(client)[0][0]
    stale = version(client, occurrence_id)
    act(client, occurrence_id, "pay", paid_on="2026-09-30")
    repeat = post_form(client, "/bills", f"/bills/occurrences/{occurrence_id}/pay",
                       {"version": stale, "paid_on": "2026-09-30"})
    assert repeat.status_code == 409
    assert client.get("/transactions").text.count("Managed by its bill") == 1


def test_an_invalid_payment_date_is_explained(client):
    ready(client)
    occurrence_id = actions(client)[0][0]
    response = act(client, occurrence_id, "pay", paid_on="2026-10-01")
    assert response.status_code == 400 and "Future transactions cannot be recorded yet." in response.text


def test_skip_and_unskip(client):
    ready(client)
    occurrence_id = actions(client)[0][0]
    act(client, occurrence_id, "skip")
    assert (occurrence_id, "unskip") in actions(client) and "Skipped" in client.get("/bills").text
    act(client, occurrence_id, "unskip")
    assert (occurrence_id, "pay") in actions(client)


def test_changing_one_occurrence(client):
    ready(client)
    occurrence_id = actions(client)[0][0]
    response = act(client, occurrence_id, "edit", amount="99.50", due_date="2026-09-28")
    assert response.status_code == 303
    page = client.get(f"/bills/occurrences/{occurrence_id}").text
    assert "€99.50" in page and "2026-09-28" in page
    bad = act(client, occurrence_id, "edit", amount="0", due_date="nope")
    assert bad.status_code == 400 and "Enter an amount greater than zero." in bad.text


def test_changing_this_and_future_bills(client):
    ready(client)
    october = actions(client)[-1][0]
    fields = {"name": "Phone", "amount": "130", "category_id": "4", "freq": "monthly", "interval": "1",
              "anchor_date": "2026-10-25", "until": "", "count": ""}
    assert act(client, october, "split", **fields).status_code == 303
    page = client.get("/bills").text
    assert "€120.00" in page and "€130.00" in page and "Ended" not in page
    bad = act(client, actions(client)[-1][0], "split", **{**fields, "anchor_date": "2026-09-01"})
    assert bad.status_code == 400 and "the bill you are changing" in bad.text


def test_ending_a_series(client):
    ready(client)
    page = client.get("/bills").text
    series_id = re.search(r'action="/bills/series/(\d+)/end"', page).group(1)
    series_version = re.search(r'action="/bills/series/\d+/end".*?name="version" value="(\d+)"', page, re.S).group(1)
    response = post_form(client, "/bills", f"/bills/series/{series_id}/end", {"version": series_version})
    assert response.status_code == 303
    page = client.get("/bills").text
    assert "Ended" in page and "2026-09-25" in page and "2026-10-25" not in page


def test_bill_forms_need_a_csrf_token(client):
    ready(client)
    occurrence_id = actions(client)[0][0]
    response = client.post(f"/bills/occurrences/{occurrence_id}/pay", data={"version": "1"}, headers=ORIGIN,
                           follow_redirects=False)
    assert response.status_code == 403
    assert csrf_from(client.get("/bills"))


def test_the_split_form_keeps_the_end_date(client):
    sign_up(client)
    set_up(client, opening_balance="500")
    add_bill(client, until="2027-03-25")
    october = actions(client)[-1][0]
    page = client.get(f"/bills/occurrences/{october}").text
    assert 'name="until" type="date" value="2027-03-25"' in page

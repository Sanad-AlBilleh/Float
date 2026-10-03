"""A small JSON client for /api/v1: it keeps the CSRF token and sends it as X-CSRF-Token (SRS §9)."""

PASSWORD = "correct horse battery"


class Api:
    def __init__(self, browser):
        self.browser = browser
        self.token = browser.get("/api/v1/csrf").json()["csrf_token"]

    def _headers(self, extra=None):
        return {"X-CSRF-Token": self.token, **(extra or {})}

    def get(self, path, **kwargs):
        return self.browser.get("/api/v1" + path, **kwargs)

    def send(self, method, path, body=None, headers=None):
        response = self.browser.request(method, "/api/v1" + path, json=body, headers=self._headers(headers))
        if response.headers.get("content-type", "").startswith("application/json"):
            data = response.json()
            if isinstance(data, dict) and "csrf_token" in data:
                self.token = data["csrf_token"]
        return response

    def post(self, path, body=None, headers=None):
        return self.send("POST", path, body, headers)

    def patch(self, path, body=None):
        return self.send("PATCH", path, body)

    def put(self, path, body=None):
        return self.send("PUT", path, body)

    def delete(self, path, body=None):
        return self.send("DELETE", path, body)


def signed_up(browser, username="ana", *, setup=True, opening_cents=50000):
    api = Api(browser)
    response = api.post("/auth/register", {"username": username, "display_name": username.title(),
                                            "password": PASSWORD})
    assert response.status_code == 201, response.text
    if setup:
        response = api.post("/setup", {"tracking_start": "2026-09-01", "opening_balance_cents": opening_cents,
                                       "allowance_day": 1, "planned_allowance_cents": 75000,
                                       "allowance_included": True})
        assert response.status_code == 200, response.text
    return api

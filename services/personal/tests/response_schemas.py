"""Every JSON response a test client receives is checked against the OpenAPI document (Assignment 2 §8a).

The routes build their JSON by hand, so the response schemas in openapi.json are written separately
(app/api/v1/responses.py). This hook keeps them honest: a missing field, a wrong type or a missing
``*_display`` twin fails whichever test made the request.
"""

import re

from jsonschema import Draft202012Validator

checked: set[tuple[str, str, str]] = set()  # (method, path template, status) checked in this test session


def _operations(document: dict) -> list[tuple[re.Pattern, str, str, dict]]:
    found = [(re.compile("^" + re.sub(r"\{[^/]+\}", "[^/]+", template) + "$"), template, method, operation)
             for template, operations in document["paths"].items() for method, operation in operations.items()]
    return sorted(found, key=lambda item: item[1].count("{"))  # literal paths win over templated ones


def _check(document: dict, operations, response) -> None:
    method, path = response.request.method.lower(), response.request.url.path
    for pattern, template, op_method, operation in operations:
        if op_method != method or not pattern.match(path):
            continue
        documented = operation.get("responses", {}).get(str(response.status_code), {})
        schema = documented.get("content", {}).get("application/json", {}).get("schema")
        if schema and response.headers.get("content-type", "").startswith("application/json"):
            response.read()
            validator = Draft202012Validator({**schema, "components": document.get("components", {})})
            errors = sorted(validator.iter_errors(response.json()), key=lambda error: list(error.path))
            assert not errors, (f"{method.upper()} {template} {response.status_code} does not match openapi.json: "
                                + "; ".join(f"{list(e.path)}: {e.message}" for e in errors[:5]))
            checked.add((method, template, str(response.status_code)))
        return


def install(client) -> None:
    document = client.app.openapi()
    operations = _operations(document)
    client.event_hooks = {"request": [], "response": [lambda response: _check(document, operations, response)]}

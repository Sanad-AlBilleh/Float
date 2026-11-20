"""OpenAPI response schemas for routes that return ``to_json(...)`` of the application's records.

The routes build their JSON by hand (``problems.to_json``), so FastAPI cannot see what they return. Here
each route names the record type it returns, and the schema is generated from that type with the same
rules ``to_json`` applies: dates are ISO strings, and every ``*_cents`` integer has a ``*_display``
string twin. The definitions go into ``components/schemas``; ``tests/api/test_response_schemas.py``
checks real responses against them.
"""

from typing import Any

from pydantic import TypeAdapter

REF = "#/components/schemas/{model}"
DEFINITIONS: dict[str, dict] = {}


def _with_display_twins(schema: Any) -> Any:
    if isinstance(schema, list):
        return [_with_display_twins(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    schema = {key: _with_display_twins(value) for key, value in schema.items()}
    properties = schema.get("properties")
    if isinstance(properties, dict):
        for name in list(properties):
            if name.endswith("_cents"):
                twin = name.removesuffix("_cents") + "_display"
                properties.setdefault(twin, {"type": "string", "description": f"`{name}` formatted as euros"})
    return schema


def _register(name: str, schema: dict) -> None:
    schema = _with_display_twins(schema)
    known = DEFINITIONS.get(name)
    if known is not None and known != schema:
        raise ValueError(f"two different response types are both called {name}")
    DEFINITIONS[name] = schema


def schema_of(annotation: Any) -> dict:
    """The JSON schema for ``annotation``; named types become ``$ref``s into components/schemas."""
    generated = TypeAdapter(annotation).json_schema(ref_template=REF, mode="serialization")
    for name, definition in generated.pop("$defs", {}).items():
        _register(name, definition)
    if isinstance(annotation, type) and generated.get("type") == "object":  # a record type: refer to it by name
        return named(annotation.__name__, generated)
    return _with_display_twins(generated)


def named(name: str, schema: dict) -> dict:
    """Register a hand-written object schema (for responses built as dicts) and return a reference to it."""
    _register(name, schema)
    return {"$ref": REF.format(model=name)}


def extend(base: Any, **properties: Any) -> dict:
    """``base`` (a record type) plus extra properties, as the routes do with ``{**to_json(x), ...}``."""
    return {"allOf": [schema_of(base), {"type": "object", "properties": {
        key: schema_of(value) for key, value in properties.items()}, "required": sorted(properties)}]}


def obj(**properties: Any) -> dict:
    return {"type": "object", "properties": {key: schema_of(value) if not isinstance(value, dict) else value
                                             for key, value in properties.items()},
            "required": sorted(properties)}


def returns(schema: Any, status: int = 200, description: str = "Success") -> dict:
    """Keyword arguments for a route decorator: ``@router.get(..., **returns(Transaction))``."""
    body = schema if isinstance(schema, dict) else schema_of(schema)
    return {"status_code": status,
            "responses": {status: {"description": description, "content": {"application/json": {"schema": body}}}}}


def add_to(openapi: dict) -> dict:
    schemas = openapi.setdefault("components", {}).setdefault("schemas", {})
    clash = sorted(name for name in DEFINITIONS if name in schemas and schemas[name] != DEFINITIONS[name])
    if clash:
        raise ValueError(f"response schema names already used by FastAPI: {clash}")
    schemas.update(DEFINITIONS)
    return openapi

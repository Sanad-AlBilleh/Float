"""Check that system.yaml matches the code (Assignment 2 §8a). Run by CI; exits 1 on any mismatch.

1. Every environment variable a service reads (in services/<name>/app/config.py) is listed in system.yaml,
   and nothing else is.
2. Every endpoint a service calls on the other exists in the other service's openapi.json.
3. The paths system.yaml names (OpenAPI documents, migrations) exist.
Validation against system.schema.json is a separate CI step (check-jsonschema).
"""

import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
READ = re.compile(r'(?:values\.get|_required|_integer|_number|_boolean)\(\s*(?:values,\s*)?"([A-Z_]+)"')


def main() -> int:
    system = yaml.safe_load((ROOT / "system.yaml").read_text(encoding="utf-8"))
    problems: list[str] = []
    for name, service in system["services"].items():
        config = (ROOT / service["path"] / "app" / "config.py").read_text(encoding="utf-8")
        read = set(READ.findall(config))
        listed = set(service["env"])
        problems += [f"{name}: reads {var} but system.yaml does not list it" for var in sorted(read - listed)]
        problems += [f"{name}: system.yaml lists {var} but the code never reads it" for var in sorted(listed - read)]
        for key in ("openapi", "migrations"):
            if not (ROOT / service[key]).exists():
                problems.append(f"{name}: {key} path {service[key]} does not exist")
        for call in service.get("calls", []):
            other = system["services"][call["service"]]
            document = json.loads((ROOT / other["openapi"]).read_text(encoding="utf-8"))
            offered = {f"{method.upper()} {path}" for path, ops in document["paths"].items() for method in ops}
            problems += [f"{name} calls {endpoint} on {call['service']}, which its openapi does not have"
                         for endpoint in call["endpoints"] if endpoint not in offered]
            if call["url_env"] not in service["env"]:
                problems.append(f"{name}: url_env {call['url_env']} is not in its env list")
    for problem in problems:
        print(f"::error::{problem}")
    print("system.yaml matches the code" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

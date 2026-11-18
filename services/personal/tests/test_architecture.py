"""The split's rules, checked by reading the code (SRS §6.1, Assignment 2 ADR-6).

Inside this service, domain packages do not import each other (Insights may read the others' api.py).
Across the seam: no code of the households service is here, and no query touches its tables.
"""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
DOMAINS = {"identity", "ledger", "planning", "insights"}
OTHER_SERVICE_TABLES = ("households", "memberships", "invitations", "shared_expenses", "shared_expense_splits",
                        "household_bill_series", "household_bill_participants", "household_bill_occurrences",
                        "settlements")


def imported_modules(path: Path, root: Path = ROOT) -> set[str]:
    """Fully qualified names imported by ``path``, with relative imports resolved."""
    package_parts = list(path.relative_to(root).with_suffix("").parts[:-1])
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package_parts[: len(package_parts) - node.level + 1]
                module = ".".join(base + ([node.module] if node.module else []))
            else:
                module = node.module or ""
            found.update(f"{module}.{alias.name}" for alias in node.names)
    return found


def python_files(package: str = "") -> list[Path]:
    directory = APP / package if package else APP
    return sorted(directory.rglob("*.py")) if directory.is_dir() else []


def test_domains_do_not_import_each_other():
    violations = []
    for domain in sorted(DOMAINS):
        for path in python_files(domain):
            for module in sorted(imported_modules(path)):
                parts = module.split(".")
                if len(parts) < 2 or parts[0] != "app" or parts[1] not in DOMAINS or parts[1] == domain:
                    continue
                if domain == "insights" and len(parts) >= 3 and parts[2] == "api":
                    continue
                violations.append(f"{path.relative_to(ROOT)} imports {module}")
    assert violations == []


def test_shared_kernel_has_no_io_or_domain_dependencies():
    forbidden = ("pymssql", "httpx2", "fastapi", "starlette", "app.db", "app.application", "app.api", "app.clients")
    forbidden += tuple(f"app.{domain}" for domain in DOMAINS)
    violations = [f"{path.relative_to(ROOT)} imports {module}" for path in python_files("shared")
                  for module in sorted(imported_modules(path)) if module.startswith(forbidden)]
    assert violations == []


def test_no_code_or_query_from_the_other_service():
    assert not (APP / "households").exists()
    pattern = re.compile(r"\b(FROM|JOIN|INTO|UPDATE)\s+(" + "|".join(OTHER_SERVICE_TABLES) + r")\b", re.IGNORECASE)
    hits = [f"{path.relative_to(ROOT)}: {match.group(0)}" for path in python_files()
            for match in pattern.finditer(path.read_text(encoding="utf-8"))]
    hits += [f"{path.name}: {match.group(0)}" for path in sorted((ROOT / "migrations").glob("*.sql"))
             for match in pattern.finditer(path.read_text(encoding="utf-8"))]
    assert hits == []


def test_checker_resolves_relative_and_absolute_imports(tmp_path):
    module = tmp_path / "app" / "ledger" / "service.py"
    module.parent.mkdir(parents=True)
    module.write_text("from ..planning import api\nfrom . import rules\nimport app.insights.forecast\n", encoding="utf-8")
    assert imported_modules(module, tmp_path) == {"app.planning.api", "app.ledger.rules", "app.insights.forecast"}

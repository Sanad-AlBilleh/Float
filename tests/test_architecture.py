"""Enforce the dependency rule of SRS §6.1 by reading import statements."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
DOMAINS = {"identity", "ledger", "planning", "households", "insights"}


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


def python_files(package: str) -> list[Path]:
    directory = APP / package
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
    forbidden = ("sqlite3", "fastapi", "starlette", "app.db", "app.web", "app.application", "app.api")
    forbidden += tuple(f"app.{domain}" for domain in DOMAINS)
    violations = [
        f"{path.relative_to(ROOT)} imports {module}"
        for path in python_files("shared")
        for module in sorted(imported_modules(path))
        if module.startswith(forbidden)
    ]
    assert violations == []


def test_checker_resolves_relative_and_absolute_imports(tmp_path):
    module = tmp_path / "app" / "ledger" / "service.py"
    module.parent.mkdir(parents=True)
    module.write_text(
        "from ..planning import api\nfrom . import rules\nimport app.households.service\n",
        encoding="utf-8",
    )
    assert imported_modules(module, tmp_path) == {
        "app.planning.api",
        "app.ledger.rules",
        "app.households.service",
    }

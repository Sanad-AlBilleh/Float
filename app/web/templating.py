"""The Jinja2 environment shared by every HTML route. Autoescaping is on (SRS §9)."""

from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.shared.money import format_money

TEMPLATES_DIR = Path(__file__).with_name("templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.filters["money"] = format_money

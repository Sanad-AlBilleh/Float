"""The Jinja2 environment shared by every HTML route. Autoescaping is on (SRS §9)."""

from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.shared.money import format_money

TEMPLATES_DIR = Path(__file__).with_name("templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.filters["money"] = format_money


def describe_rule(rule) -> str:
    """Plain words for a recurrence rule: "Monthly", "Every 2 weeks, until 2027-06-30", "Once"."""
    if rule.freq == "once":
        return "Once"
    unit = "week" if rule.freq == "weekly" else "month"
    text = f"{unit.title()}ly" if rule.interval == 1 else f"Every {rule.interval} {unit}s"
    if rule.until is not None:
        text += f", until {rule.until.isoformat()}"
    if rule.count is not None:
        text += f", {rule.count} time{'' if rule.count == 1 else 's'} in all"
    return text


templates.env.filters["rule"] = describe_rule

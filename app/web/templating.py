"""The Jinja2 environment shared by every HTML route. Autoescaping is on (SRS §9)."""

from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.shared.money import cents_to_input, format_money

TEMPLATES_DIR = Path(__file__).with_name("templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.filters["money"] = format_money
templates.env.filters["money_input"] = cents_to_input


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


# The fixed categories (migration 0001) as an icon and a colour tone for lists and charts.
CATEGORY_STYLES = {
    1: ("cart", "violet"), 2: ("utensils", "orange"), 3: ("bus", "blue"), 4: ("house", "teal"),
    5: ("bolt", "amber"), 6: ("repeat", "pink"), 7: ("book", "indigo"), 8: ("music", "green"),
    9: ("heart", "red"), 10: ("plane", "sky"), 11: ("dots", "slate"),
}
TONE_COLOURS = {
    "violet": "#7c5cff", "orange": "#f08a3c", "blue": "#3b8bf5", "teal": "#2fa59a", "amber": "#e7b008",
    "pink": "#e75a9b", "indigo": "#5b6be8", "green": "#3fb36d", "red": "#e5534b", "sky": "#38b2d8",
    "slate": "#8a94a6",
}


def category_style(category_id) -> dict:
    icon, tone = CATEGORY_STYLES.get(category_id, ("dots", "slate"))
    return {"icon": icon, "tone": tone, "colour": TONE_COLOURS[tone]}


def money_whole(cents: int) -> str:
    """``123456`` → ``€1,234`` (the big part of a hero number)."""
    return format_money(cents).rsplit(".", 1)[0]


def money_fraction(cents: int) -> str:
    """``123456`` → ``.56`` (shown smaller and dimmer, as in banking apps)."""
    return "." + format_money(cents).rsplit(".", 1)[1]


def initials(name: str) -> str:
    parts = [part for part in (name or "?").split() if part]
    return "".join(part[0] for part in parts[:2]).upper() or "?"


templates.env.globals["category_style"] = category_style
templates.env.filters["money_whole"] = money_whole
templates.env.filters["money_fraction"] = money_fraction
templates.env.filters["initials"] = initials

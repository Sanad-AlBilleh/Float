"""Insights' public interface. Code outside the insights package imports only this module."""

from app.insights.alerts import (
    AlertFacts,
    AlertSpec,
    BillFact,
    BudgetFact,
    GoalFact,
    HouseholdExpenseFact,
    SettlementFact,
    UnusualFact,
    desired_alerts,
)
from app.insights.alerts_store import (
    Alert,
    alert_row_count,
    dismiss,
    get_cursor,
    list_alerts,
    mark_read,
    set_cursor,
    sync_alerts,
)
from app.insights.anomaly import is_unusual, lower_median, unusual_threshold
from app.insights.consumption import ShareRow, consumption_by_category, variable_consumption
from app.insights.forecast import DayProjection, Forecast, ForecastInputs, compute_forecast, pace_window_days
from app.insights.safe_to_spend import Preview, SafeToSpend, SafeToSpendInputs, compute, preview

__all__ = [
    "Alert",
    "AlertFacts",
    "AlertSpec",
    "BillFact",
    "BudgetFact",
    "GoalFact",
    "HouseholdExpenseFact",
    "SettlementFact",
    "UnusualFact",
    "alert_row_count",
    "desired_alerts",
    "dismiss",
    "get_cursor",
    "list_alerts",
    "mark_read",
    "set_cursor",
    "sync_alerts",
    "DayProjection",
    "Forecast",
    "ForecastInputs",
    "Preview",
    "SafeToSpend",
    "SafeToSpendInputs",
    "ShareRow",
    "compute",
    "compute_forecast",
    "is_unusual",
    "lower_median",
    "consumption_by_category",
    "pace_window_days",
    "preview",
    "unusual_threshold",
    "variable_consumption",
]

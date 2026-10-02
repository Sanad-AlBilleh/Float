"""Insights' public interface. Code outside the insights package imports only this module."""

from app.insights.consumption import ShareRow, consumption_by_category, variable_consumption
from app.insights.forecast import DayProjection, Forecast, ForecastInputs, compute_forecast, pace_window_days
from app.insights.safe_to_spend import Preview, SafeToSpend, SafeToSpendInputs, compute, preview

__all__ = [
    "DayProjection",
    "Forecast",
    "ForecastInputs",
    "Preview",
    "SafeToSpend",
    "SafeToSpendInputs",
    "ShareRow",
    "compute",
    "compute_forecast",
    "consumption_by_category",
    "pace_window_days",
    "preview",
    "variable_consumption",
]

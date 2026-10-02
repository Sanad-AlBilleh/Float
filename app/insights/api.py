"""Insights' public interface. Code outside the insights package imports only this module."""

from app.insights.safe_to_spend import Preview, SafeToSpend, SafeToSpendInputs, compute, preview

__all__ = ["Preview", "SafeToSpend", "SafeToSpendInputs", "compute", "preview"]

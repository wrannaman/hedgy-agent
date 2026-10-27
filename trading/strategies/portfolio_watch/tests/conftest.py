"""Synthetic account mapping; tests never depend on private local settings."""
import pytest
from strategies.portfolio_watch import rules


@pytest.fixture(autouse=True)
def synthetic_accounts(monkeypatch):
    monkeypatch.setattr(rules, "ACCOUNT_TAX_TREATMENT", {
        "101": "taxable", "102": "taxable", "201": "tax_deferred", "301": "tax_free"})
    monkeypatch.setattr(rules, "ACCOUNT_BUCKET", {
        "101": "taxable", "102": "taxable", "201": "401k", "301": "roth"})
    monkeypatch.setattr(rules, "BUCKET_LABEL", {
        "taxable": "taxable book", "401k": "401k", "roth": "Roth"})

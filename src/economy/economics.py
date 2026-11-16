"""Transparent unit-economics calculator; estimates are not sales forecasts."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UnitEconomics:
    price_minor: int
    variable_cost_minor: int
    fixed_setup_cost_minor: int = 0
    platform_fee_bps: int = 0
    payment_fee_bps: int = 0
    fixed_fee_per_sale_minor: int = 0
    currency: str = "USD"

    def calculate(self, units: int = 1) -> dict:
        if units < 1:
            raise ValueError("units must be at least 1")
        for name in ("price_minor", "variable_cost_minor", "fixed_setup_cost_minor", "fixed_fee_per_sale_minor"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} cannot be negative")
        if self.price_minor <= 0:
            raise ValueError("price_minor must be greater than zero")
        for name in ("platform_fee_bps", "payment_fee_bps"):
            if not 0 <= getattr(self, name) <= 10000:
                raise ValueError(f"{name} must be between 0 and 10000")
        if len(self.currency) != 3 or not self.currency.isalpha():
            raise ValueError("currency must be a three-letter code")
        gross = self.price_minor * units
        percentage_fees = (self.price_minor * (self.platform_fee_bps + self.payment_fee_bps) + 9999) // 10000
        per_unit_net = self.price_minor - percentage_fees - self.fixed_fee_per_sale_minor - self.variable_cost_minor
        total_variable_profit = per_unit_net * units
        net_after_setup = total_variable_profit - self.fixed_setup_cost_minor
        break_even_units = (
            (self.fixed_setup_cost_minor + per_unit_net - 1) // per_unit_net
            if per_unit_net > 0 else None
        )
        return {
            "currency": self.currency.upper(),
            "units_assumed": units,
            "gross_revenue_minor": gross,
            "estimated_platform_and_payment_fees_minor": percentage_fees * units,
            "estimated_variable_cost_minor": self.variable_cost_minor * units,
            "fixed_setup_cost_minor": self.fixed_setup_cost_minor,
            "estimated_net_profit_minor": net_after_setup,
            "estimated_net_margin_bps": round(net_after_setup * 10000 / gross) if gross else 0,
            "break_even_units": break_even_units,
            "profitable_per_unit_before_setup": per_unit_net > 0,
            "notice": "Scenario estimate only, not a sales forecast. Enter real provider fees, taxes, refunds, and costs before relying on it.",
        }

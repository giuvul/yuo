"""Money as integer micro-units plus an ISO 4217 currency. Never floats in storage."""

from dataclasses import dataclass
from decimal import Decimal

MICRO = 1_000_000


@dataclass(frozen=True, slots=True)
class Money:
    micros: int
    currency: str = "USD"

    def __post_init__(self) -> None:
        if len(self.currency) != 3 or not self.currency.isupper():
            raise ValueError(f"not an ISO 4217 code: {self.currency!r}")

    @classmethod
    def of(cls, amount: str | Decimal, currency: str = "USD") -> Money:
        return cls(int((Decimal(amount) * MICRO).to_integral_value()), currency)

    def __add__(self, other: Money) -> Money:
        if other.currency != self.currency:
            raise ValueError(f"currency mismatch: {self.currency} + {other.currency}")
        return Money(self.micros + other.micros, self.currency)

    def __str__(self) -> str:
        return f"{Decimal(self.micros) / MICRO:.6f} {self.currency}"

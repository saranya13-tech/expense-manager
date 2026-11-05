"""Balance and ledger calculations shared by the website and the API."""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.db.models import Count, DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce

from .models import Transaction

ZERO = Decimal("0")
KINDS = [k for k, _ in Transaction.KIND_CHOICES]


def _sum(kind):
    return Coalesce(
        Sum("transactions__amount", filter=Q(transactions__kind=kind)),
        Value(ZERO),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )


def books_with_totals(queryset):
    """Annotate books with added/income/expense/entry_count and set .balance on each."""
    books = list(
        queryset.annotate(
            added=_sum(Transaction.BALANCE),
            income=_sum(Transaction.INCOME),
            expense=_sum(Transaction.EXPENSE),
            entry_count=Count("transactions"),
        )
    )
    for b in books:
        b.balance = b.added + b.income - b.expense
    return books


def parse_month(value, today):
    """'2026-11' -> date(2026, 11, 1); anything invalid -> first day of today's month."""
    try:
        y, m = (int(x) for x in (value or "").split("-"))
        return date(y, m, 1)
    except ValueError:
        return today.replace(day=1)


def shift_month(d, delta):
    m = d.month - 1 + delta
    return date(d.year + m // 12, m % 12 + 1, 1)


@dataclass
class Ledger:
    balance: Decimal
    totals: dict
    month: date
    month_totals: dict
    days: list = field(default_factory=list)
    has_entries: bool = False

    @property
    def month_in(self):
        return self.month_totals[Transaction.BALANCE] + self.month_totals[Transaction.INCOME]

    @property
    def month_net(self):
        return self.month_in - self.month_totals[Transaction.EXPENSE]


def build_ledger(book, month, query=""):
    """Walk all entries oldest-first so every entry and day knows the balance after it,
    then return the requested month (newest first), optionally filtered by remark."""
    all_tx = list(book.transactions.order_by("date", "created_at", "id"))
    totals = dict.fromkeys(KINDS, ZERO)
    running = ZERO
    closing_by_day = {}
    for t in all_tx:
        running += t.signed_amount
        t.running = running
        totals[t.kind] += t.amount
        closing_by_day[t.date] = running

    month_tx = [t for t in reversed(all_tx) if t.date.year == month.year and t.date.month == month.month]
    month_totals = dict.fromkeys(KINDS, ZERO)
    for t in month_tx:
        month_totals[t.kind] += t.amount
    if query:
        month_tx = [t for t in month_tx if query.lower() in t.remark.lower()]

    days = {}
    for t in month_tx:
        d = days.setdefault(t.date, {"date": t.date, "items": [], "in": ZERO, "out": ZERO, "closing": closing_by_day[t.date]})
        d["items"].append(t)
        d["out" if t.kind == Transaction.EXPENSE else "in"] += t.amount

    return Ledger(running, totals, month, month_totals, list(days.values()), bool(all_tx))

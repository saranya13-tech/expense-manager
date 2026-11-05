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
    """Annotate books with per-kind totals and entry_count, and set .balance on each."""
    books = list(
        queryset.annotate(
            added=_sum(Transaction.BALANCE),
            income=_sum(Transaction.INCOME),
            expense=_sum(Transaction.EXPENSE),
            gave=_sum(Transaction.GAVE),
            got=_sum(Transaction.GOT),
            entry_count=Count("transactions"),
        )
    )
    for b in books:
        b.balance = b.added + b.income + b.got - b.expense - b.gave
    _attach_people_totals(books)
    return books


def _attach_people_totals(books):
    """Set .to_receive / .to_pay on each book from its Gave/Got entries (one query for all books)."""
    by_book = {b.pk: [] for b in books}
    if by_book:
        for t in Transaction.objects.filter(book_id__in=by_book, kind__in=Transaction.PERSON_KINDS):
            by_book[t.book_id].append(t)
    for b in books:
        people = people_summary(by_book[b.pk])
        b.to_receive = sum((p.net for p in people if p.net > 0), ZERO)
        b.to_pay = sum((-p.net for p in people if p.net < 0), ZERO)


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


def person_key(name):
    """People are matched by name, ignoring case and extra spaces."""
    return " ".join((name or "").split()).casefold()


@dataclass
class Person:
    name: str
    gave: Decimal = ZERO
    got: Decimal = ZERO
    entry_count: int = 0

    @property
    def net(self):
        """Positive: they owe you (you will get). Negative: you owe them (you will give)."""
        return self.gave - self.got

    @property
    def abs_net(self):
        return abs(self.net)

    @property
    def status(self):
        return "get" if self.net > 0 else "give" if self.net < 0 else "settled"


@dataclass
class Ledger:
    balance: Decimal
    totals: dict
    month: date
    month_totals: dict
    days: list = field(default_factory=list)
    has_entries: bool = False
    people: list = field(default_factory=list)
    person: str = ""

    @property
    def month_in(self):
        t = self.month_totals
        return t[Transaction.BALANCE] + t[Transaction.INCOME] + t[Transaction.GOT]

    @property
    def month_out(self):
        return self.month_totals[Transaction.EXPENSE] + self.month_totals[Transaction.GAVE]

    @property
    def month_net(self):
        return self.month_in - self.month_out

    @property
    def to_receive(self):
        return sum((p.net for p in self.people if p.net > 0), ZERO)

    @property
    def to_pay(self):
        return sum((-p.net for p in self.people if p.net < 0), ZERO)


def people_summary(transactions):
    """Group Gave/Got entries by person. Unsettled people first (largest amount), then settled."""
    people = {}
    for t in transactions:
        if t.kind not in Transaction.PERSON_KINDS or not t.person.strip():
            continue
        p = people.setdefault(person_key(t.person), Person(name=" ".join(t.person.split())))
        p.entry_count += 1
        if t.kind == Transaction.GAVE:
            p.gave += t.amount
        else:
            p.got += t.amount
    return sorted(people.values(), key=lambda p: (p.net == 0, -p.abs_net, p.name.casefold()))


def build_ledger(book, month, query="", person=""):
    """Walk all entries oldest-first so every entry and day knows the balance after it.

    Returns the requested month (newest first), optionally filtered by remark/person text.
    If `person` is given, returns that person's entries from all months instead.
    """
    all_tx = list(book.transactions.order_by("date", "created_at", "id"))
    totals = dict.fromkeys(KINDS, ZERO)
    running = ZERO
    closing_by_day = {}
    for t in all_tx:
        running += t.signed_amount
        t.running = running
        totals[t.kind] += t.amount
        closing_by_day[t.date] = running

    newest_first = list(reversed(all_tx))
    if person:
        key = person_key(person)
        month_tx = [t for t in newest_first if person_key(t.person) == key]
    else:
        month_tx = [t for t in newest_first if t.date.year == month.year and t.date.month == month.month]

    month_totals = dict.fromkeys(KINDS, ZERO)
    for t in month_tx:
        month_totals[t.kind] += t.amount
    if query:
        q = query.casefold()
        month_tx = [t for t in month_tx if q in t.remark.casefold() or q in t.person.casefold()]

    days = {}
    for t in month_tx:
        d = days.setdefault(t.date, {"date": t.date, "items": [], "in": ZERO, "out": ZERO, "closing": closing_by_day[t.date]})
        d["items"].append(t)
        d["out" if t.kind in Transaction.MONEY_OUT else "in"] += t.amount

    return Ledger(
        balance=running,
        totals=totals,
        month=month,
        month_totals=month_totals,
        days=list(days.values()),
        has_entries=bool(all_tx),
        people=people_summary(all_tx),
        person=" ".join(person.split()) if person else "",
    )


# ---------------------------------------------------------------------------
# Clearing old months (free up space, keep balances)
# ---------------------------------------------------------------------------

@dataclass
class CleanupPreview:
    keep_from: date
    entry_count: int
    balance: Decimal          # book balance at the end of the cleared period
    people: list              # Person objects with a non-zero net, carried forward
    first_date: date | None
    last_date: date | None

    @property
    def carry_date(self):
        from datetime import timedelta
        return self.keep_from - timedelta(days=1)


def cleanup_preview(book, keep_from):
    old = list(book.transactions.filter(date__lt=keep_from).order_by("date", "created_at", "id"))
    return CleanupPreview(
        keep_from=keep_from,
        entry_count=len(old),
        balance=sum((t.signed_amount for t in old), ZERO),
        people=[p for p in people_summary(old) if p.net != 0],
        first_date=old[0].date if old else None,
        last_date=old[-1].date if old else None,
    )


def clear_before(book, keep_from):
    """Delete all entries dated before `keep_from` and replace them with carried-forward entries,
    so the book balance and every person's dues stay exactly the same. Returns (deleted, created)."""
    from datetime import timedelta

    from django.db import connection, transaction

    label = keep_from.strftime("%b %Y")
    carry_date = keep_from - timedelta(days=1)
    with transaction.atomic():
        preview = cleanup_preview(book, keep_from)
        if not preview.entry_count:
            return 0, 0
        carried = []
        people_signed = ZERO
        for p in preview.people:
            kind = Transaction.GAVE if p.net > 0 else Transaction.GOT
            carried.append(Transaction(book=book, kind=kind, amount=p.abs_net, person=p.name, date=carry_date,
                                       remark=f"Carried forward (before {label})"))
            people_signed -= p.net  # Gave of +net counts as -net; Got of -net counts as -net
        cash = preview.balance - people_signed
        if cash > 0:
            carried.append(Transaction(book=book, kind=Transaction.BALANCE, amount=cash, date=carry_date,
                                       remark=f"Carried forward balance (before {label})"))
        elif cash < 0:
            carried.append(Transaction(book=book, kind=Transaction.EXPENSE, amount=-cash, date=carry_date,
                                       remark=f"Carried forward negative balance (before {label})"))
        deleted, _ = book.transactions.filter(date__lt=keep_from).delete()
        Transaction.objects.bulk_create(carried)
    if connection.vendor == "sqlite" and not connection.in_atomic_block:
        with connection.cursor() as cursor:
            cursor.execute("VACUUM")  # actually shrink the database file (not allowed inside a transaction)
    return deleted, len(carried)


def cleanup_months(book, today):
    """Months the user can choose as 'keep from': after the oldest entry, up to the current month."""
    first = book.transactions.order_by("date").values_list("date", flat=True).first()
    if not first:
        return []
    months = []
    m = shift_month(first.replace(day=1), 1)
    end = today.replace(day=1)
    while m <= end:
        months.append(m)
        m = shift_month(m, 1)
    return list(reversed(months))

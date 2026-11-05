from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.db.models import Count, DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import BookForm, TransactionForm
from .models import Book, Transaction

ZERO = Decimal("0")


def _sum(kind):
    return Coalesce(
        Sum("transactions__amount", filter=Q(transactions__kind=kind)),
        Value(ZERO),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )


def _books_with_totals(user):
    books = list(
        user.books.annotate(
            added=_sum(Transaction.BALANCE),
            income=_sum(Transaction.INCOME),
            expense=_sum(Transaction.EXPENSE),
            entry_count=Count("transactions"),
        )
    )
    for b in books:
        b.balance = b.added + b.income - b.expense
    return books


def _parse_month(value, today):
    try:
        y, m = (int(x) for x in (value or "").split("-"))
        return date(y, m, 1)
    except ValueError:
        return today.replace(day=1)


def _shift_month(d, delta):
    m = d.month - 1 + delta
    return date(d.year + m // 12, m % 12 + 1, 1)


def register(request):
    if request.user.is_authenticated:
        return redirect("book_list")
    form = UserCreationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        book = Book.objects.create(user=user, name="Personal")
        login(request, user)
        messages.success(request, f"Welcome, {user.username}! We made a “Personal” book for you. Start by adding a balance.")
        return redirect("book_detail", pk=book.pk)
    return render(request, "registration/register.html", {"form": form})


@login_required
def book_list(request):
    form = BookForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        book = form.save(commit=False)
        book.user = request.user
        book.save()
        messages.success(request, f"Book “{book.name}” created.")
        return redirect("book_detail", pk=book.pk)
    books = _books_with_totals(request.user)
    return render(request, "tracker/book_list.html", {
        "books": books,
        "form": form,
        "show_form": request.method == "POST" or not books,
    })


@login_required
def book_detail(request, pk):
    book = get_object_or_404(Book, pk=pk, user=request.user)
    today = timezone.localdate()
    month = _parse_month(request.GET.get("month"), today)
    query = request.GET.get("q", "").strip()

    if request.method == "POST":
        form = TransactionForm(request.POST)
        if form.is_valid():
            t = form.save(commit=False)
            t.book = book
            t.save()
            messages.success(request, f"{t.get_kind_display()} of {book.currency}{t.amount:,.2f} added.")
            return redirect(f"{request.path}?month={t.date:%Y-%m}")
    else:
        form = TransactionForm(initial={"date": today, "kind": Transaction.EXPENSE})

    # Walk all entries oldest-first so every entry and day knows the balance after it.
    all_tx = list(book.transactions.order_by("date", "created_at", "id"))
    totals = {k: ZERO for k, _ in Transaction.KIND_CHOICES}
    running = ZERO
    closing_by_day = {}
    for t in all_tx:
        running += t.signed_amount
        t.running = running
        totals[t.kind] += t.amount
        closing_by_day[t.date] = running

    month_tx = [t for t in reversed(all_tx) if t.date.year == month.year and t.date.month == month.month]
    month_totals = {k: ZERO for k, _ in Transaction.KIND_CHOICES}
    for t in month_tx:
        month_totals[t.kind] += t.amount
    if query:
        month_tx = [t for t in month_tx if query.lower() in t.remark.lower()]

    days = {}
    for t in month_tx:
        d = days.setdefault(t.date, {"date": t.date, "items": [], "in": ZERO, "out": ZERO, "closing": closing_by_day[t.date]})
        d["items"].append(t)
        d["out" if t.kind == Transaction.EXPENSE else "in"] += t.amount

    month_in = month_totals[Transaction.BALANCE] + month_totals[Transaction.INCOME]
    return render(request, "tracker/book_detail.html", {
        "book": book,
        "books": request.user.books.all(),
        "form": form,
        "balance": running,
        "totals": totals,
        "month": month,
        "month_value": month.strftime("%Y-%m"),
        "prev_month": _shift_month(month, -1).strftime("%Y-%m"),
        "next_month": _shift_month(month, 1).strftime("%Y-%m"),
        "is_current_month": month == today.replace(day=1),
        "month_totals": month_totals,
        "month_in": month_in,
        "month_net": month_in - month_totals[Transaction.EXPENSE],
        "days": list(days.values()),
        "query": query,
        "has_entries": bool(all_tx),
    })


@login_required
def book_edit(request, pk):
    book = get_object_or_404(Book, pk=pk, user=request.user)
    form = BookForm(request.POST or None, instance=book, user=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Book updated.")
        return redirect("book_detail", pk=book.pk)
    return render(request, "tracker/book_edit.html", {"form": form, "book": book})


@login_required
@require_POST
def book_delete(request, pk):
    book = get_object_or_404(Book, pk=pk, user=request.user)
    name = book.name
    book.delete()
    messages.success(request, f"Book “{name}” and all its entries were deleted.")
    return redirect("book_list")


@login_required
def entry_edit(request, pk):
    t = get_object_or_404(Transaction, pk=pk, book__user=request.user)
    form = TransactionForm(request.POST or None, instance=t)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Entry updated.")
        return redirect(f"/books/{t.book_id}/?month={t.date:%Y-%m}")
    return render(request, "tracker/entry_edit.html", {"form": form, "t": t, "book": t.book})


@login_required
@require_POST
def entry_delete(request, pk):
    t = get_object_or_404(Transaction, pk=pk, book__user=request.user)
    book_id, month = t.book_id, t.date.strftime("%Y-%m")
    t.delete()
    messages.success(request, "Entry deleted.")
    return redirect(f"/books/{book_id}/?month={month}")

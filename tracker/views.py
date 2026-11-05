from collections import OrderedDict
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import TransactionForm
from .models import Transaction


def _totals(qs):
    totals = {k: Decimal("0") for k, _ in Transaction.KIND_CHOICES}
    for t in qs:
        totals[t.kind] += t.amount
    return totals


def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = UserCreationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, f"Welcome, {user.username}! Start by adding your balance.")
        return redirect("dashboard")
    return render(request, "registration/register.html", {"form": form})


@login_required
def dashboard(request):
    today = timezone.localdate()
    month = request.GET.get("month") or today.strftime("%Y-%m")
    try:
        year, mon = (int(x) for x in month.split("-"))
    except ValueError:
        year, mon = today.year, today.month
        month = today.strftime("%Y-%m")

    if request.method == "POST":
        form = TransactionForm(request.POST)
        if form.is_valid():
            t = form.save(commit=False)
            t.user = request.user
            t.save()
            messages.success(request, f"{t.get_kind_display()} of {t.amount} added.")
            return redirect(f"{request.path}?month={t.date:%Y-%m}")
    else:
        form = TransactionForm(initial={"date": today})

    # Running balance across ALL entries (oldest first) so each day shows its closing balance.
    all_tx = list(request.user.transactions.order_by("date", "created_at"))
    running = Decimal("0")
    closing_by_day = {}
    for t in all_tx:
        running += t.signed_amount
        closing_by_day[t.date] = running
    current_balance = running
    overall = _totals(all_tx)

    month_tx = [t for t in reversed(all_tx) if t.date.year == year and t.date.month == mon]
    month_totals = _totals(month_tx)

    days = OrderedDict()
    for t in month_tx:
        day = days.setdefault(t.date, {"date": t.date, "items": [], "in": Decimal("0"), "out": Decimal("0")})
        day["items"].append(t)
        if t.kind == Transaction.EXPENSE:
            day["out"] += t.amount
        else:
            day["in"] += t.amount
    for d in days.values():
        d["closing"] = closing_by_day[d["date"]]

    return render(request, "tracker/dashboard.html", {
        "form": form,
        "current_balance": current_balance,
        "overall": overall,
        "month": month,
        "month_totals": month_totals,
        "month_net": month_totals["BALANCE"] + month_totals["INCOME"] - month_totals["EXPENSE"],
        "days": days.values(),
    })


@login_required
def edit_transaction(request, pk):
    t = get_object_or_404(Transaction, pk=pk, user=request.user)
    form = TransactionForm(request.POST or None, instance=t)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Entry updated.")
        return redirect(f"/?month={t.date:%Y-%m}")
    return render(request, "tracker/edit.html", {"form": form, "t": t})


@login_required
@require_POST
def delete_transaction(request, pk):
    t = get_object_or_404(Transaction, pk=pk, user=request.user)
    month = t.date.strftime("%Y-%m")
    t.delete()
    messages.success(request, "Entry deleted.")
    return redirect(f"/?month={month}")

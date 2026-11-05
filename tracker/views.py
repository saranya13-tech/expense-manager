from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import BookForm, TransactionForm
from .models import Book, Transaction
from .services import books_with_totals, build_ledger, parse_month, shift_month

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
    books = books_with_totals(request.user.books.all())
    return render(request, "tracker/book_list.html", {
        "books": books,
        "form": form,
        "show_form": request.method == "POST" or not books,
    })


@login_required
def book_detail(request, pk):
    book = get_object_or_404(Book, pk=pk, user=request.user)
    today = timezone.localdate()
    month = parse_month(request.GET.get("month"), today)
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

    ledger = build_ledger(book, month, query)
    return render(request, "tracker/book_detail.html", {
        "book": book,
        "books": request.user.books.all(),
        "form": form,
        "balance": ledger.balance,
        "totals": ledger.totals,
        "month": month,
        "month_value": month.strftime("%Y-%m"),
        "prev_month": shift_month(month, -1).strftime("%Y-%m"),
        "next_month": shift_month(month, 1).strftime("%Y-%m"),
        "is_current_month": month == today.replace(day=1),
        "month_totals": ledger.month_totals,
        "month_in": ledger.month_in,
        "month_net": ledger.month_net,
        "days": ledger.days,
        "query": query,
        "has_entries": ledger.has_entries,
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
        return redirect(f"{reverse('book_detail', args=[t.book_id])}?month={t.date:%Y-%m}")
    back_url = f"{reverse('book_detail', args=[t.book_id])}?month={t.date:%Y-%m}"
    return render(request, "tracker/entry_edit.html", {"form": form, "t": t, "book": t.book, "back_url": back_url})


@login_required
@require_POST
def entry_delete(request, pk):
    t = get_object_or_404(Transaction, pk=pk, book__user=request.user)
    book_id, month = t.book_id, t.date.strftime("%Y-%m")
    t.delete()
    messages.success(request, "Entry deleted.")
    return redirect(f"/books/{book_id}/?month={month}")

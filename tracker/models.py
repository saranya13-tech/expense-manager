from django.conf import settings
from django.db import models
from django.utils import timezone


class Book(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="books")
    name = models.CharField(max_length=100)
    currency = models.CharField(max_length=5, default="₹", help_text="Symbol shown before amounts, e.g. ₹, $, €")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "name"], name="unique_book_name_per_user"),
        ]

    def __str__(self):
        return self.name


class Transaction(models.Model):
    BALANCE = "BALANCE"
    INCOME = "INCOME"
    EXPENSE = "EXPENSE"
    KIND_CHOICES = [
        (BALANCE, "Add Balance"),
        (INCOME, "Income"),
        (EXPENSE, "Expense"),
    ]

    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="transactions")
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=EXPENSE)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateField(default=timezone.localdate)
    remark = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    @property
    def signed_amount(self):
        return -self.amount if self.kind == self.EXPENSE else self.amount

    def __str__(self):
        return f"{self.date} {self.get_kind_display()} {self.amount} {self.remark}"

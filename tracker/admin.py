from django.contrib import admin

from .models import Book, Transaction


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "currency", "created_at")
    list_filter = ("user",)
    search_fields = ("name",)


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("date", "book", "kind", "amount", "remark")
    list_filter = ("book__user", "book", "kind", "date")
    search_fields = ("remark",)

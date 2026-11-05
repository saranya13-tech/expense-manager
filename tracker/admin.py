from django.contrib import admin

from .models import Transaction


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("user", "date", "kind", "amount", "remark")
    list_filter = ("user", "kind", "date")
    search_fields = ("remark",)

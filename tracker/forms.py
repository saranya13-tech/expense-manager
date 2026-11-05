from django import forms

from .models import Book, Transaction


class BookForm(forms.ModelForm):
    class Meta:
        model = Book
        fields = ["name", "currency"]
        labels = {"name": "Book name"}
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "e.g. Personal, Business, Trip to Goa"}),
            "currency": forms.TextInput(attrs={"placeholder": "₹", "maxlength": 5}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        qs = Book.objects.filter(user=self.user, name__iexact=name)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("You already have a book with this name.")
        return name


class TransactionForm(forms.ModelForm):
    class Meta:
        model = Transaction
        fields = ["kind", "amount", "date", "remark"]
        labels = {"kind": "Type"}
        widgets = {
            "kind": forms.RadioSelect,
            "date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "amount": forms.NumberInput(attrs={"step": "0.01", "min": "0.01", "placeholder": "0.00", "inputmode": "decimal"}),
            "remark": forms.TextInput(attrs={"placeholder": "What was it for? e.g. Groceries, Salary, Rent"}),
        }

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount <= 0:
            raise forms.ValidationError("Amount must be greater than zero.")
        return amount

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
        fields = ["kind", "amount", "person", "date", "remark"]
        labels = {"kind": "Type", "person": "Person"}
        widgets = {
            "kind": forms.RadioSelect,
            "date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "amount": forms.NumberInput(attrs={"step": "0.01", "min": "0.01", "placeholder": "0.00", "inputmode": "decimal"}),
            "remark": forms.TextInput(attrs={"placeholder": "What was it for? e.g. Groceries, Salary, Rent"}),
            "person": forms.TextInput(attrs={"placeholder": "Name, e.g. Ravi", "list": "people-names", "autocomplete": "off"}),
        }

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount <= 0:
            raise forms.ValidationError("Amount must be greater than zero.")
        return amount

    def clean(self):
        cleaned = super().clean()
        kind = cleaned.get("kind")
        person = " ".join((cleaned.get("person") or "").split())
        if kind in Transaction.PERSON_KINDS:
            if not person:
                verb = "gave money to" if kind == Transaction.GAVE else "got money from"
                self.add_error("person", f"Enter the name of the person you {verb}.")
        else:
            person = ""  # only Gave/Got entries belong to a person
        cleaned["person"] = person
        return cleaned

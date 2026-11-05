from django.db import migrations


def forwards(apps, schema_editor):
    Transaction = apps.get_model("tracker", "Transaction")
    Book = apps.get_model("tracker", "Book")
    user_ids = Transaction.objects.filter(book__isnull=True).values_list("user_id", flat=True).distinct()
    for user_id in user_ids:
        book, _ = Book.objects.get_or_create(user_id=user_id, name="My Book")
        Transaction.objects.filter(user_id=user_id, book__isnull=True).update(book=book)


class Migration(migrations.Migration):
    dependencies = [("tracker", "0002_books")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]

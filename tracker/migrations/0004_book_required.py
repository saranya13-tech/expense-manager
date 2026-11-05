import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def restore_user_from_book(apps, schema_editor):
    """Only used when rolling back: refill the old Transaction.user column."""
    Transaction = apps.get_model("tracker", "Transaction")
    for t in Transaction.objects.select_related("book"):
        t.user_id = t.book.user_id
        t.save(update_fields=["user"])


class Migration(migrations.Migration):
    dependencies = [
        ("tracker", "0003_move_entries_into_books"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="transaction",
            name="book",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="transactions",
                to="tracker.book",
            ),
        ),
        migrations.AlterField(
            model_name="transaction",
            name="user",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="transactions",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(migrations.RunPython.noop, restore_user_from_book),
        migrations.RemoveField(model_name="transaction", name="user"),
    ]

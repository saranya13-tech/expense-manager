from django.contrib.auth.models import User
from django.test import TestCase

from .models import Transaction


class AuthTests(TestCase):
    def test_dashboard_requires_login(self):
        r = self.client.get("/")
        self.assertRedirects(r, "/accounts/login/?next=/")

    def test_register_logs_in(self):
        r = self.client.post("/accounts/register/", {
            "username": "alice", "password1": "S3cure-pass-123", "password2": "S3cure-pass-123",
        })
        self.assertRedirects(r, "/")
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_login_logout(self):
        User.objects.create_user("bob", password="S3cure-pass-123")
        r = self.client.post("/accounts/login/", {"username": "bob", "password": "S3cure-pass-123"})
        self.assertRedirects(r, "/")
        r = self.client.post("/accounts/logout/")
        self.assertRedirects(r, "/accounts/login/")


class DashboardTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("u1", password="pw-12345678")
        self.other = User.objects.create_user("u2", password="pw-12345678")
        self.client.force_login(self.user)

    def test_balance_flow(self):
        c = self.client
        c.post("/", {"date": "2026-11-01", "kind": "BALANCE", "amount": "1000", "remark": "Opening"})
        c.post("/", {"date": "2026-11-02", "kind": "EXPENSE", "amount": "150.50", "remark": "Groceries"})
        c.post("/", {"date": "2026-11-02", "kind": "INCOME", "amount": "200", "remark": "Freelance"})
        r = c.get("/?month=2026-11")
        self.assertEqual(str(r.context["current_balance"]), "1049.50")
        days = list(r.context["days"])
        self.assertEqual(str(days[0]["closing"]), "1049.50")
        self.assertEqual(str(days[1]["closing"]), "1000.00")
        self.assertTrue(all(t.user == self.user for t in Transaction.objects.all()))

    def test_users_see_only_their_own_data(self):
        Transaction.objects.create(user=self.other, kind="BALANCE", amount=5000, remark="secret")
        r = self.client.get("/")
        self.assertEqual(r.context["current_balance"], 0)
        self.assertNotContains(r, "secret")

    def test_cannot_edit_or_delete_others_entries(self):
        t = Transaction.objects.create(user=self.other, kind="EXPENSE", amount=50)
        self.assertEqual(self.client.get(f"/edit/{t.pk}/").status_code, 404)
        self.assertEqual(self.client.post(f"/delete/{t.pk}/").status_code, 404)
        self.assertTrue(Transaction.objects.filter(pk=t.pk).exists())

    def test_edit_and_delete_own(self):
        t = Transaction.objects.create(user=self.user, kind="EXPENSE", amount=50, remark="x")
        self.client.post(f"/edit/{t.pk}/", {"date": t.date, "kind": "EXPENSE", "amount": "75", "remark": "y"})
        t.refresh_from_db()
        self.assertEqual(t.amount, 75)
        self.client.post(f"/delete/{t.pk}/")
        self.assertFalse(Transaction.objects.exists())

    def test_rejects_non_positive(self):
        self.client.post("/", {"date": "2026-11-01", "kind": "EXPENSE", "amount": "0"})
        self.assertFalse(Transaction.objects.exists())

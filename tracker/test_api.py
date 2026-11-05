from decimal import Decimal

from django.contrib.auth.models import User
from django.core.cache import cache
from unittest import mock

from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from .api.views import AuthThrottle
from .models import Book, Transaction

API = "/api/v1"


class AuthApiTests(APITestCase):
    def setUp(self):
        cache.clear()

    def test_register_returns_token_and_creates_personal_book(self):
        r = self.client.post(f"{API}/auth/register/", {"username": "alice", "password": "S3cure-pass-123"})
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["user"]["username"], "alice")
        self.assertEqual(Token.objects.get(user__username="alice").key, r.data["token"])
        self.assertEqual(list(Book.objects.values_list("name", flat=True)), ["Personal"])

    def test_register_validation(self):
        User.objects.create_user("Taken", password="x")
        r = self.client.post(f"{API}/auth/register/", {"username": "taken", "password": "S3cure-pass-123"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("username", r.data)
        r = self.client.post(f"{API}/auth/register/", {"username": "new", "password": "123"})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(User.objects.filter(username="new").exists())

    def test_login_me_logout(self):
        User.objects.create_user("bob", password="S3cure-pass-123")
        self.assertEqual(self.client.post(f"{API}/auth/login/", {"username": "bob", "password": "bad"}).status_code, 401)
        r = self.client.post(f"{API}/auth/login/", {"username": "bob", "password": "S3cure-pass-123"})
        self.assertEqual(r.status_code, 200)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {r.data['token']}")
        self.assertEqual(self.client.get(f"{API}/auth/me/").data["username"], "bob")
        self.assertEqual(self.client.post(f"{API}/auth/logout/").status_code, 204)
        self.assertEqual(self.client.get(f"{API}/auth/me/").status_code, 401)

    def test_requires_token(self):
        self.assertEqual(self.client.get(f"{API}/books/").status_code, 401)

    @mock.patch.object(AuthThrottle, "THROTTLE_RATES", {"auth": "3/min"})
    def test_login_is_rate_limited(self):
        codes = [self.client.post(f"{API}/auth/login/", {"username": "x", "password": "y"}).status_code for _ in range(4)]
        self.assertEqual(codes[-1], 429)

    def test_docs_and_schema_are_public(self):
        self.assertEqual(self.client.get(f"{API}/schema/").status_code, 200)
        self.assertEqual(self.client.get(f"{API}/docs/").status_code, 200)


class BookApiTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("u1", password="pw-12345678")
        self.other = User.objects.create_user("u2", password="pw-12345678")
        self.client.force_authenticate(self.user)

    def add(self, book_id, kind, amount, date="2026-11-01", remark=""):
        return self.client.post(f"{API}/books/{book_id}/entries/",
                                {"kind": kind, "amount": amount, "date": date, "remark": remark})

    def test_book_crud_with_totals(self):
        r = self.client.post(f"{API}/books/", {"name": "Home", "currency": "₹"})
        self.assertEqual(r.status_code, 201, r.data)
        bid = r.data["id"]
        self.assertEqual(r.data["balance"], "0.00")
        self.add(bid, "BALANCE", "1000")
        self.add(bid, "EXPENSE", "250.50")
        self.add(bid, "INCOME", "100")
        r = self.client.get(f"{API}/books/{bid}/")
        self.assertEqual((r.data["balance"], r.data["added"], r.data["income"], r.data["expense"], r.data["entry_count"]),
                         ("849.50", "1000.00", "100.00", "250.50", 3))
        r = self.client.patch(f"{API}/books/{bid}/", {"name": "House"})
        self.assertEqual((r.data["name"], r.data["balance"]), ("House", "849.50"))
        self.assertEqual(self.client.delete(f"{API}/books/{bid}/").status_code, 204)
        self.assertFalse(Transaction.objects.exists())

    def test_list_shows_only_my_books(self):
        Book.objects.create(user=self.user, name="Mine")
        Book.objects.create(user=self.other, name="Theirs")
        names = [b["name"] for b in self.client.get(f"{API}/books/").data]
        self.assertEqual(names, ["Mine"])

    def test_duplicate_book_name(self):
        Book.objects.create(user=self.user, name="Home")
        r = self.client.post(f"{API}/books/", {"name": "HOME"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("name", r.data)

    def test_ledger_matches_website_logic(self):
        b = Book.objects.create(user=self.user, name="B")
        self.add(b.id, "BALANCE", "1000", "2026-11-01", "Opening")
        self.add(b.id, "EXPENSE", "150.50", "2026-11-02", "Groceries")
        self.add(b.id, "INCOME", "200", "2026-11-02", "Gift")
        self.add(b.id, "EXPENSE", "99", "2026-10-15", "Old")
        r = self.client.get(f"{API}/books/{b.id}/ledger/?month=2026-11")
        d = r.data
        self.assertEqual(d["balance"], "950.50")
        self.assertEqual((d["month"], d["prev_month"], d["next_month"]), ("2026-11", "2026-10", "2026-12"))
        self.assertEqual(d["month_totals"]["EXPENSE"], "150.50")
        self.assertEqual(d["month_net"], "1049.50")
        self.assertEqual([day["date"] for day in d["days"]], ["2026-11-02", "2026-11-01"])
        self.assertEqual(d["days"][0]["closing"], "950.50")
        self.assertEqual(d["days"][0]["money_in"], "200.00")
        self.assertEqual([i["running"] for i in d["days"][0]["items"]], ["950.50", "750.50"])
        r = self.client.get(f"{API}/books/{b.id}/ledger/?month=2026-11&q=groc")
        self.assertEqual([i["remark"] for day in r.data["days"] for i in day["items"]], ["Groceries"])

    def test_entry_validation(self):
        b = Book.objects.create(user=self.user, name="B")
        r = self.add(b.id, "EXPENSE", "0")
        self.assertEqual(r.status_code, 400)
        r = self.add(b.id, "NOPE", "5")
        self.assertEqual(r.status_code, 400)

    def test_entry_update_and_delete(self):
        b = Book.objects.create(user=self.user, name="B")
        eid = self.add(b.id, "EXPENSE", "10", remark="x").data["id"]
        r = self.client.patch(f"{API}/entries/{eid}/", {"amount": "12.25", "remark": "y", "book": 999})
        self.assertEqual((r.data["amount"], r.data["remark"], r.data["book"]), ("12.25", "y", b.id))
        self.assertEqual(self.client.delete(f"{API}/entries/{eid}/").status_code, 204)

    def test_cannot_access_other_users_data(self):
        theirs = Book.objects.create(user=self.other, name="Secret")
        t = Transaction.objects.create(book=theirs, kind="BALANCE", amount=Decimal("9999"))
        for method, url in [("get", f"/books/{theirs.id}/"), ("get", f"/books/{theirs.id}/ledger/"),
                            ("patch", f"/books/{theirs.id}/"), ("delete", f"/books/{theirs.id}/"),
                            ("get", f"/entries/{t.id}/"), ("patch", f"/entries/{t.id}/"), ("delete", f"/entries/{t.id}/")]:
            self.assertEqual(getattr(self.client, method)(API + url).status_code, 404, url)
        self.assertEqual(self.add(theirs.id, "EXPENSE", "1").status_code, 404)
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertTrue(Book.objects.filter(pk=theirs.pk).exists())


class GaveGotApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("a", password="pw-12345678")
        self.client.force_authenticate(self.user)
        self.book = Book.objects.create(user=self.user, name="B")

    def add(self, **data):
        data.setdefault("date", "2026-11-01")
        return self.client.post(f"{API}/books/{self.book.id}/entries/", data)

    def test_person_required(self):
        r = self.add(kind="GAVE", amount="10")
        self.assertEqual(r.status_code, 400)
        self.assertIn("person", r.data)

    def test_people_in_ledger_and_book(self):
        self.add(kind="BALANCE", amount="1000")
        self.add(kind="GAVE", amount="300", person="Ravi")
        self.add(kind="GOT", amount="500", person="Meena")
        r = self.client.get(f"{API}/books/{self.book.id}/ledger/?month=2026-11")
        self.assertEqual(r.data["balance"], "1200.00")
        self.assertEqual((r.data["to_receive"], r.data["to_pay"]), ("300.00", "500.00"))
        self.assertEqual({p["name"]: p["status"] for p in r.data["people"]}, {"Ravi": "get", "Meena": "give"})
        self.assertEqual(r.data["totals"]["GAVE"], "300.00")
        b = self.client.get(f"{API}/books/{self.book.id}/").data
        self.assertEqual((b["balance"], b["to_receive"], b["to_pay"]), ("1200.00", "300.00", "500.00"))
        r = self.client.get(f"{API}/books/{self.book.id}/ledger/?person=ravi")
        self.assertEqual([i["person"] for d in r.data["days"] for i in d["items"]], ["Ravi"])

    def test_changing_kind_clears_person(self):
        eid = self.add(kind="GAVE", amount="10", person="Ravi").data["id"]
        r = self.client.patch(f"{API}/entries/{eid}/", {"kind": "EXPENSE"})
        self.assertEqual(r.data["person"], "")

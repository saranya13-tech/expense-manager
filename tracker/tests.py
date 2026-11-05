from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from .models import Book, Transaction


class AuthTests(TestCase):
    def test_pages_require_login(self):
        self.assertRedirects(self.client.get("/"), "/accounts/login/?next=/")

    def test_register_creates_default_book_and_logs_in(self):
        r = self.client.post("/accounts/register/", {
            "username": "alice", "password1": "S3cure-pass-123", "password2": "S3cure-pass-123",
        })
        book = Book.objects.get(user__username="alice")
        self.assertEqual(book.name, "Personal")
        self.assertRedirects(r, f"/books/{book.pk}/")

    def test_login_logout(self):
        User.objects.create_user("bob", password="S3cure-pass-123")
        r = self.client.post("/accounts/login/", {"username": "bob", "password": "S3cure-pass-123"})
        self.assertRedirects(r, "/")
        self.assertRedirects(self.client.post("/accounts/logout/"), "/accounts/login/")


class BookTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("u1", password="pw-12345678")
        self.other = User.objects.create_user("u2", password="pw-12345678")
        self.client.force_login(self.user)

    def add(self, book, kind, amount, d="2026-11-01", remark=""):
        return self.client.post(f"/books/{book.pk}/", {"kind": kind, "amount": amount, "date": d, "remark": remark})

    def test_create_book(self):
        r = self.client.post("/", {"name": "Business", "currency": "$"})
        book = Book.objects.get(name="Business")
        self.assertEqual(book.user, self.user)
        self.assertRedirects(r, f"/books/{book.pk}/")

    def test_duplicate_book_name_rejected(self):
        Book.objects.create(user=self.user, name="Home")
        r = self.client.post("/", {"name": "home", "currency": "₹"})
        self.assertContains(r, "already have a book")
        self.assertEqual(Book.objects.filter(user=self.user).count(), 1)
        # Same name is fine for a different user.
        Book.objects.create(user=self.other, name="Home")

    def test_each_book_has_its_own_balance(self):
        home = Book.objects.create(user=self.user, name="Home")
        biz = Book.objects.create(user=self.user, name="Biz")
        self.add(home, "BALANCE", "1000", remark="Opening")
        self.add(home, "EXPENSE", "150.50", "2026-11-02", "Groceries")
        self.add(home, "INCOME", "200", "2026-11-02", "Gift")
        self.add(biz, "BALANCE", "5000")
        self.add(biz, "EXPENSE", "1000")

        r = self.client.get(f"/books/{home.pk}/?month=2026-11")
        self.assertEqual(r.context["balance"], Decimal("1049.50"))
        days = r.context["days"]
        self.assertEqual(days[0]["closing"], Decimal("1049.50"))
        self.assertEqual(days[1]["closing"], Decimal("1000.00"))
        self.assertContains(r, "Groceries")
        shown = [t.amount for d in days for t in d["items"]]
        self.assertEqual(sorted(shown), [Decimal("150.50"), Decimal("200"), Decimal("1000")])

        r = self.client.get(f"/books/{biz.pk}/?month=2026-11")
        self.assertEqual(r.context["balance"], Decimal("4000"))

        r = self.client.get("/")
        balances = {b.name: b.balance for b in r.context["books"]}
        self.assertEqual(balances, {"Home": Decimal("1049.50"), "Biz": Decimal("4000")})
        self.assertContains(r, "₹1,049.50")

    def test_running_balance_per_entry_and_search(self):
        b = Book.objects.create(user=self.user, name="B")
        self.add(b, "BALANCE", "500", remark="Start")
        self.add(b, "EXPENSE", "100", remark="Taxi")
        self.add(b, "EXPENSE", "50", remark="Coffee")
        r = self.client.get(f"/books/{b.pk}/?month=2026-11")
        items = r.context["days"][0]["items"]
        self.assertEqual([t.running for t in items], [Decimal("350"), Decimal("400"), Decimal("500")])
        r = self.client.get(f"/books/{b.pk}/?month=2026-11&q=taxi")
        self.assertEqual([t.remark for t in r.context["days"][0]["items"]], ["Taxi"])
        # Search filters the list but not the balance.
        self.assertEqual(r.context["balance"], Decimal("350"))

    def test_month_navigation(self):
        b = Book.objects.create(user=self.user, name="B")
        r = self.client.get(f"/books/{b.pk}/?month=2026-01")
        self.assertEqual(r.context["prev_month"], "2025-12")
        self.assertEqual(r.context["next_month"], "2026-02")
        r = self.client.get(f"/books/{b.pk}/?month=garbage")
        self.assertEqual(r.status_code, 200)

    def test_cannot_touch_other_users_books_or_entries(self):
        theirs = Book.objects.create(user=self.other, name="Secret")
        t = Transaction.objects.create(book=theirs, kind="BALANCE", amount=9999)
        self.assertEqual(self.client.get(f"/books/{theirs.pk}/").status_code, 404)
        self.assertEqual(self.add(theirs, "EXPENSE", "1").status_code, 404)
        self.assertEqual(self.client.get(f"/books/{theirs.pk}/edit/").status_code, 404)
        self.assertEqual(self.client.post(f"/books/{theirs.pk}/delete/").status_code, 404)
        self.assertEqual(self.client.get(f"/entries/{t.pk}/edit/").status_code, 404)
        self.assertEqual(self.client.post(f"/entries/{t.pk}/delete/").status_code, 404)
        self.assertNotContains(self.client.get("/"), "Secret")
        self.assertEqual(Transaction.objects.count(), 1)

    def test_edit_and_delete_entry(self):
        b = Book.objects.create(user=self.user, name="B")
        t = Transaction.objects.create(book=b, kind="EXPENSE", amount=50, remark="x")
        r = self.client.post(f"/entries/{t.pk}/edit/", {"date": "2026-11-03", "kind": "INCOME", "amount": "75", "remark": "y"})
        self.assertRedirects(r, f"/books/{b.pk}/?month=2026-11")
        t.refresh_from_db()
        self.assertEqual((t.kind, t.amount, t.remark), ("INCOME", 75, "y"))
        self.client.post(f"/entries/{t.pk}/delete/")
        self.assertFalse(Transaction.objects.exists())

    def test_rename_and_delete_book(self):
        b = Book.objects.create(user=self.user, name="Old")
        Transaction.objects.create(book=b, kind="BALANCE", amount=10)
        self.client.post(f"/books/{b.pk}/edit/", {"name": "New", "currency": "€"})
        b.refresh_from_db()
        self.assertEqual((b.name, b.currency), ("New", "€"))
        self.assertContains(self.client.get(f"/books/{b.pk}/edit/"), "Delete book")
        self.assertRedirects(self.client.post(f"/books/{b.pk}/delete/"), "/")
        self.assertFalse(Book.objects.exists())
        self.assertFalse(Transaction.objects.exists())

    def test_rejects_non_positive(self):
        b = Book.objects.create(user=self.user, name="B")
        self.add(b, "EXPENSE", "0")
        self.assertFalse(Transaction.objects.exists())

    def test_all_pages_render(self):
        b = Book.objects.create(user=self.user, name="B")
        t = Transaction.objects.create(book=b, kind="EXPENSE", amount=5)
        for url in ["/", f"/books/{b.pk}/", f"/books/{b.pk}/edit/", f"/entries/{t.pk}/edit/"]:
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.client.logout()
        for url in ["/accounts/login/", "/accounts/register/"]:
            self.assertEqual(self.client.get(url).status_code, 200, url)


class MobileUiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("m", password="pw-12345678")
        self.client.force_login(self.user)
        self.book = Book.objects.create(user=self.user, name="Home")

    def test_brand_and_home_screen_support(self):
        r = self.client.get("/")
        self.assertContains(r, "<title>My books · Spendly</title>", html=False)
        self.assertContains(r, 'rel="manifest"')
        self.assertContains(r, 'rel="apple-touch-icon"')
        self.assertNotContains(r, 'class="back"')  # home page has no back button

    def test_book_page_has_back_to_books_and_add_entry_sheet(self):
        r = self.client.get(f"/books/{self.book.pk}/")
        self.assertContains(r, '<a class="back" href="/"', html=False)
        self.assertContains(r, 'id="entry-sheet"')
        self.assertContains(r, "data-open-sheet")
        self.assertContains(r, 'data-date-offset="-1"')

    def test_invalid_entry_reopens_the_sheet(self):
        r = self.client.post(f"/books/{self.book.pk}/", {"kind": "EXPENSE", "amount": "0", "date": "2026-11-01"})
        self.assertContains(r, 'class="has-fab sheet-open"', html=False)

    def test_settings_and_entry_pages_go_back_to_the_book(self):
        r = self.client.get(f"/books/{self.book.pk}/edit/")
        self.assertContains(r, f'<a class="back" href="/books/{self.book.pk}/"', html=False)
        t = Transaction.objects.create(book=self.book, kind="EXPENSE", amount=5, date="2026-10-03")
        r = self.client.get(f"/entries/{t.pk}/edit/")
        self.assertContains(r, f'<a class="back" href="/books/{self.book.pk}/?month=2026-10"', html=False)
        self.assertContains(r, "Delete entry")


class PwaTests(TestCase):
    def test_manifest(self):
        r = self.client.get("/manifest.webmanifest")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/manifest+json")
        m = r.json()
        self.assertEqual((m["name"], m["short_name"], m["display"], m["start_url"]), ("Spendly", "Spendly", "standalone", "/"))
        sizes = {i["sizes"] for i in m["icons"]}
        self.assertEqual(sizes, {"192x192", "512x512"})
        self.assertIn("maskable", {i["purpose"] for i in m["icons"]})
        for icon in m["icons"]:
            self.assertTrue(icon["src"].startswith("/static/tracker/icon-"))

    def test_service_worker_served_from_root(self):
        r = self.client.get("/sw.js")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/javascript")
        self.assertEqual(r["Service-Worker-Allowed"], "/")
        self.assertEqual(r["Cache-Control"], "no-cache")
        body = r.content.decode()
        self.assertIn("const OFFLINE_URL = '/offline/'", body)
        self.assertIn("req.mode === 'navigate'", body)

    def test_offline_page_is_public(self):
        r = self.client.get("/offline/")
        self.assertContains(r, "You're offline")

    def test_pages_link_manifest_and_register_worker(self):
        r = self.client.get("/accounts/login/")
        self.assertContains(r, '<link rel="manifest" href="/manifest.webmanifest">', html=False)
        self.assertContains(r, "serviceWorker.register('/sw.js'", html=False)
        user = User.objects.create_user("p", password="pw-12345678")
        self.client.force_login(user)
        self.assertContains(self.client.get("/"), 'id="install-app"')

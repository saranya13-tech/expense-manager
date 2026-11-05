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


class GaveGotTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("g", password="pw-12345678")
        self.client.force_login(self.user)
        self.book = Book.objects.create(user=self.user, name="Home")

    def add(self, kind, amount, person="", d="2026-11-01", remark=""):
        return self.client.post(f"/books/{self.book.pk}/",
                                {"kind": kind, "amount": amount, "person": person, "date": d, "remark": remark})

    def test_person_required_for_gave_and_got(self):
        r = self.add("GAVE", "100")
        self.assertContains(r, "Enter the name of the person you gave money to")
        r = self.add("GOT", "100", person="   ")
        self.assertContains(r, "Enter the name of the person you got money from")
        self.assertFalse(Transaction.objects.exists())

    def test_person_is_dropped_for_other_kinds(self):
        self.add("EXPENSE", "10", person="Ravi")
        self.assertEqual(Transaction.objects.get().person, "")

    def test_balance_and_people(self):
        self.add("BALANCE", "1000")
        self.add("GAVE", "300", "Ravi")
        self.add("GOT", "100", "ravi ")        # same person, different case/spaces
        self.add("GOT", "500", "Meena")         # you borrowed from Meena
        self.add("GAVE", "50", "Arun")
        self.add("GOT", "50", "Arun")           # settled
        r = self.client.get(f"/books/{self.book.pk}/?month=2026-11")
        # 1000 - 300 + 100 + 500 - 50 + 50
        self.assertEqual(r.context["balance"], Decimal("1300"))
        people = {p.name: (p.net, p.status) for p in r.context["people"]}
        self.assertEqual(people["Ravi"], (Decimal("200"), "get"))
        self.assertEqual(people["Meena"], (Decimal("-500"), "give"))
        self.assertEqual(people["Arun"], (Decimal("0"), "settled"))
        self.assertEqual((r.context["to_receive"], r.context["to_pay"]), (Decimal("200"), Decimal("500")))
        self.assertEqual(r.context["month_out"], Decimal("350"))
        self.assertContains(r, "You will get")
        # Books list shows the same dues
        r = self.client.get("/")
        b = r.context["books"][0]
        self.assertEqual((b.balance, b.to_receive, b.to_pay), (Decimal("1300"), Decimal("200"), Decimal("500")))

    def test_person_filter_shows_all_months(self):
        self.add("GAVE", "300", "Ravi", "2026-09-10")
        self.add("GOT", "100", "Ravi", "2026-11-02")
        self.add("EXPENSE", "20", d="2026-11-02", remark="Tea")
        r = self.client.get(f"/books/{self.book.pk}/?person=RAVI")
        items = [t for d in r.context["days"] for t in d["items"]]
        self.assertEqual([str(t.amount) for t in items], ["100.00", "300.00"])
        self.assertEqual(r.context["person_summary"].net, Decimal("200"))
        self.assertContains(r, "owes you")

    def test_search_matches_person(self):
        self.add("GAVE", "300", "Ravi")
        r = self.client.get(f"/books/{self.book.pk}/?month=2026-11&q=rav")
        self.assertEqual(len(r.context["days"]), 1)


class CleanupTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("c", password="pw-12345678")
        self.client.force_login(self.user)
        self.book = Book.objects.create(user=self.user, name="Home")

    def tx(self, kind, amount, d, person=""):
        return Transaction.objects.create(book=self.book, kind=kind, amount=Decimal(amount), date=d, person=person)

    def snapshot(self):
        from .services import build_ledger, parse_month
        from datetime import date as _d
        led = build_ledger(self.book, parse_month("2026-11", _d(2026, 11, 5)))
        return led.balance, {p.name: p.net for p in led.people if p.net}

    def test_clear_keeps_balance_and_dues(self):
        self.tx("BALANCE", "5000", "2026-08-01")
        self.tx("EXPENSE", "1200", "2026-08-15")
        self.tx("GAVE", "700", "2026-09-01", "Ravi")
        self.tx("GOT", "200", "2026-09-20", "Ravi")
        self.tx("GOT", "900", "2026-09-25", "Meena")
        self.tx("GAVE", "100", "2026-09-26", "Arun")
        self.tx("GOT", "100", "2026-09-27", "Arun")
        self.tx("INCOME", "300", "2026-10-03")
        self.tx("EXPENSE", "50", "2026-11-02")
        before = self.snapshot()

        r = self.client.get(f"/books/{self.book.pk}/edit/?keep_from=2026-10")
        self.assertEqual(r.context["preview"].entry_count, 7)
        self.assertContains(r, "Clear 7 old entries")
        self.assertContains(r, "Kept as carried-forward entries on 30 Sep 2026")
        self.assertContains(r, "Ravi: owes you <b class=\"num\">₹500.00</b>", html=False)
        self.assertContains(r, "Meena: you owe <b class=\"num\">₹900.00</b>", html=False)

        r = self.client.post(f"/books/{self.book.pk}/cleanup/", {"keep_from": "2026-10"})
        self.assertRedirects(r, f"/books/{self.book.pk}/")
        self.assertEqual(self.snapshot(), before)               # balance + dues unchanged
        old = self.book.transactions.filter(date__lt="2026-10-01")
        self.assertEqual(old.count(), 3)                        # Ravi, Meena, cash (Arun settled)
        self.assertTrue(all(t.date.isoformat() == "2026-09-30" for t in old))
        self.assertEqual(self.book.transactions.filter(date__gte="2026-10-01").count(), 2)

    def test_negative_balance_is_carried(self):
        self.tx("EXPENSE", "400", "2026-09-01")
        before = self.snapshot()
        self.client.post(f"/books/{self.book.pk}/cleanup/", {"keep_from": "2026-10"})
        self.assertEqual(self.snapshot(), before)
        t = self.book.transactions.get()
        self.assertEqual((t.kind, t.amount), ("EXPENSE", Decimal("400")))

    def test_invalid_month_and_other_users(self):
        self.tx("BALANCE", "10", "2026-09-01")
        r = self.client.post(f"/books/{self.book.pk}/cleanup/", {"keep_from": "2030-01"}, follow=True)
        self.assertContains(r, "Please choose a valid month")
        self.assertEqual(self.book.transactions.count(), 1)
        other = User.objects.create_user("o", password="pw-12345678")
        theirs = Book.objects.create(user=other, name="T")
        self.assertEqual(self.client.post(f"/books/{theirs.pk}/cleanup/", {"keep_from": "2026-10"}).status_code, 404)
        self.assertEqual(self.client.get(f"/books/{theirs.pk}/export.csv").status_code, 404)

    def test_export_csv(self):
        self.tx("BALANCE", "100", "2026-09-01")
        self.tx("GAVE", "30", "2026-09-02", "Ravi")
        r = self.client.get(f"/books/{self.book.pk}/export.csv")
        self.assertEqual(r["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn('filename="home-', r["Content-Disposition"])
        rows = r.content.decode("utf-8-sig").splitlines()
        self.assertEqual(rows[0], "Date,Type,Amount,Person,Remark,Balance after,Currency")
        self.assertEqual(rows[2], "2026-09-02,Gave,-30.00,Ravi,,70.00,₹")


class ThemeTests(TestCase):
    def test_theme_picker_and_early_script(self):
        user = User.objects.create_user("t", password="pw-12345678")
        self.client.force_login(user)
        r = self.client.get("/")
        self.assertContains(r, 'data-theme-choice="dark"')
        self.assertContains(r, 'data-accent-choice="emerald"')
        html = r.content.decode()
        self.assertLess(html.index("spendly-theme"), html.index("app.css"))  # applied before CSS loads

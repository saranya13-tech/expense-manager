from django.contrib.auth import authenticate
from django.db import transaction as db_transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.authtoken.models import Token
from rest_framework.decorators import action, api_view, permission_classes, throttle_classes
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle

from ..models import Book, Transaction
from ..services import books_with_totals, build_ledger, parse_month, shift_month
from .serializers import (
    AuthResponseSerializer, BookSerializer, LedgerSerializer, LoginSerializer,
    RegisterSerializer, TransactionSerializer, UserSerializer,
)


class AuthThrottle(SimpleRateThrottle):
    """Limits login/register attempts per IP address (rate set in settings: 'auth')."""
    scope = "auth"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


def _auth_response(user, code=status.HTTP_200_OK):
    token, _ = Token.objects.get_or_create(user=user)
    return Response({"token": token.key, "user": UserSerializer(user).data}, status=code)


@extend_schema(request=RegisterSerializer, responses={201: AuthResponseSerializer}, tags=["auth"],
               summary="Create an account (also creates a 'Personal' book) and get a token")
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@throttle_classes([AuthThrottle])
def register(request):
    s = RegisterSerializer(data=request.data)
    s.is_valid(raise_exception=True)
    with db_transaction.atomic():
        user = s.save()
        Book.objects.create(user=user, name="Personal")
    return _auth_response(user, status.HTTP_201_CREATED)


@extend_schema(request=LoginSerializer, responses={200: AuthResponseSerializer}, tags=["auth"],
               summary="Log in and get a token")
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@throttle_classes([AuthThrottle])
def login(request):
    s = LoginSerializer(data=request.data)
    s.is_valid(raise_exception=True)
    user = authenticate(request, **s.validated_data)
    if user is None:
        raise AuthenticationFailed("Incorrect username or password.")
    return _auth_response(user)


@extend_schema(request=None, responses={204: None}, tags=["auth"],
               summary="Log out (revokes the token on all devices)")
@api_view(["POST"])
def logout(request):
    Token.objects.filter(user=request.user).delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(responses=UserSerializer, tags=["auth"], summary="Current user")
@api_view(["GET"])
def me(request):
    return Response(UserSerializer(request.user).data)


@extend_schema(tags=["books"])
class BookViewSet(viewsets.ModelViewSet):
    """Books, each with its own balance. Totals are included on every response."""
    serializer_class = BookSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):  # schema generation has no user
            return Book.objects.none()
        return Book.objects.filter(user=self.request.user)

    def _with_totals(self, book):
        return books_with_totals(Book.objects.filter(pk=book.pk))[0]

    def list(self, request, *args, **kwargs):
        books = books_with_totals(self.get_queryset())
        return Response(self.get_serializer(books, many=True).data)

    def retrieve(self, request, *args, **kwargs):
        return Response(self.get_serializer(self._with_totals(self.get_object())).data)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def create(self, request, *args, **kwargs):
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        self.perform_create(s)
        return Response(self.get_serializer(self._with_totals(s.instance)).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        s = self.get_serializer(self.get_object(), data=request.data, partial=partial)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(self.get_serializer(self._with_totals(s.instance)).data)

    @extend_schema(
        summary="Ledger for one month: balances, totals and entries grouped by day",
        parameters=[
            OpenApiParameter("month", str, description="YYYY-MM (default: current month)"),
            OpenApiParameter("q", str, description="Filter entries by remark (case-insensitive)"),
        ],
        responses=LedgerSerializer,
    )
    @action(detail=True, methods=["get"])
    def ledger(self, request, pk=None):
        book = self.get_object()
        month = parse_month(request.query_params.get("month"), timezone.localdate())
        led = build_ledger(book, month, request.query_params.get("q", "").strip())
        data = {
            "book": self._with_totals(book),
            "balance": led.balance,
            "totals": led.totals,
            "month": month.strftime("%Y-%m"),
            "prev_month": shift_month(month, -1).strftime("%Y-%m"),
            "next_month": shift_month(month, 1).strftime("%Y-%m"),
            "month_totals": led.month_totals,
            "month_in": led.month_in,
            "month_net": led.month_net,
            "has_entries": led.has_entries,
            "days": led.days,
        }
        return Response(LedgerSerializer(data, context=self.get_serializer_context()).data)

    @extend_schema(summary="Add an entry to this book", request=TransactionSerializer,
                   responses={201: TransactionSerializer})
    @action(detail=True, methods=["post"], url_path="entries")
    def add_entry(self, request, pk=None):
        book = self.get_object()
        s = TransactionSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        s.save(book=book)
        return Response(s.data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["entries"])
class EntryViewSet(mixins.RetrieveModelMixin, mixins.UpdateModelMixin, mixins.DestroyModelMixin,
                   viewsets.GenericViewSet):
    """Read, edit or delete a single entry. Create entries via POST /books/{id}/entries/."""
    serializer_class = TransactionSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Transaction.objects.none()
        return Transaction.objects.filter(book__user=self.request.user)

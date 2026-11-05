from django.contrib.auth import password_validation
from django.contrib.auth.models import User
from rest_framework import serializers

from ..models import Book, Transaction


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username"]


class RegisterSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    def validate_username(self, value):
        value = value.strip()
        User.username_validator(value)
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("A user with that username already exists.")
        return value

    def validate(self, attrs):
        password_validation.validate_password(attrs["password"], User(username=attrs["username"]))
        return attrs

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True, style={"input_type": "password"})


class AuthResponseSerializer(serializers.Serializer):
    token = serializers.CharField()
    user = UserSerializer()


class BookSerializer(serializers.ModelSerializer):
    balance = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True, default=0)
    added = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True, default=0)
    income = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True, default=0)
    expense = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True, default=0)
    entry_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Book
        fields = ["id", "name", "currency", "created_at", "balance", "added", "income", "expense", "entry_count"]
        read_only_fields = ["created_at"]

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("This field may not be blank.")
        qs = Book.objects.filter(user=self.context["request"].user, name__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("You already have a book with this name.")
        return value


class TransactionSerializer(serializers.ModelSerializer):
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = Transaction
        fields = ["id", "book", "kind", "kind_display", "amount", "date", "remark", "created_at"]
        read_only_fields = ["book", "created_at"]

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Amount must be greater than zero.")
        return value


class LedgerEntrySerializer(TransactionSerializer):
    running = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True,
                                       help_text="Book balance right after this entry.")

    class Meta(TransactionSerializer.Meta):
        fields = TransactionSerializer.Meta.fields + ["running"]


class KindTotalsSerializer(serializers.Serializer):
    BALANCE = serializers.DecimalField(max_digits=14, decimal_places=2)
    INCOME = serializers.DecimalField(max_digits=14, decimal_places=2)
    EXPENSE = serializers.DecimalField(max_digits=14, decimal_places=2)


class LedgerDaySerializer(serializers.Serializer):
    date = serializers.DateField()
    money_in = serializers.DecimalField(max_digits=14, decimal_places=2, source="in")
    money_out = serializers.DecimalField(max_digits=14, decimal_places=2, source="out")
    closing = serializers.DecimalField(max_digits=14, decimal_places=2, help_text="Balance at end of day.")
    items = LedgerEntrySerializer(many=True)


class LedgerSerializer(serializers.Serializer):
    book = BookSerializer()
    balance = serializers.DecimalField(max_digits=14, decimal_places=2)
    totals = KindTotalsSerializer()
    month = serializers.CharField(help_text="YYYY-MM")
    prev_month = serializers.CharField()
    next_month = serializers.CharField()
    month_totals = KindTotalsSerializer()
    month_in = serializers.DecimalField(max_digits=14, decimal_places=2)
    month_net = serializers.DecimalField(max_digits=14, decimal_places=2)
    has_entries = serializers.BooleanField()
    days = LedgerDaySerializer(many=True)

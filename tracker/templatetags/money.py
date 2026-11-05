from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def money(value, symbol=""):
    """1234.5 -> '₹1,234.50'; -1234.5 -> '-₹1,234.50'."""
    try:
        value = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return value
    sign = "-" if value < 0 else ""
    return f"{sign}{symbol}{abs(value):,.2f}"

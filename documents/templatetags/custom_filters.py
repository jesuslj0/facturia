from django import template

register = template.Library()

@register.filter
def spanish_currency(value):
    """
    Convierte número a formato español: 12345.67 -> 12.345,67
    """
    try:
        value = float(value)
        # primero separa miles con punto, decimales con coma
        return "{:,.2f}".format(value).replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return value
"""Filtros de formatação do padrão brasileiro."""
from django import template

register = template.Library()


@register.filter
def moeda(valor):
    """
    Formata um número no padrão monetário brasileiro: 1.234.567,89.

    Aplicado apenas a valores financeiros — evita o USE_THOUSAND_SEPARATOR
    global, que agruparia também anos e outros inteiros (ex.: "2.026").
    """
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return valor
    texto = f"{numero:,.2f}"  # 1,234,567.89
    return texto.replace(",", "\x00").replace(".", ",").replace("\x00", ".")

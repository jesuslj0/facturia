from django.db.models import Q
from .models import FinancialMovement

def get_filtered_movements(request, base_qs=None):
    filters = {
        "query": request.GET.get("q"),
        "start": request.GET.get("start"),
        "end": request.GET.get("end"),
        "category": request.GET.get("category"),
        "method": request.GET.get("method"),
        "is_reconciled": request.GET.get("is_reconciled"),
        "has_receipt": request.GET.get("has_receipt"),
        "min_amount": request.GET.get("min_amount"),
        "max_amount": request.GET.get("max_amount"),
    }

    filters = {k: v for k, v in filters.items() if v}

    client = request.user.client

    if base_qs is None:
        base_qs = FinancialMovement.objects.filter(client=client)
    
    if filters.get("query"):
        base_qs = base_qs.filter(
            Q(description__icontains=filters["query"])
            | Q(category__name__icontains=filters["query"])
        )
    if filters.get("start"):
        base_qs = base_qs.filter(date__gte=filters["start"])
    if filters.get("end"):
        base_qs = base_qs.filter(date__lte=filters["end"])
    if filters.get("category"):
        base_qs = base_qs.filter(category=filters["category"])
    if filters.get("method"):
        base_qs = base_qs.filter(payment_method=filters["method"])
    if filters.get("is_reconciled"):
        base_qs = base_qs.filter(is_reconciled=True)
    if filters.get("has_receipt"):
        base_qs = base_qs.exclude(receipt_name__isnull=True)
    if filters.get("min_amount"):
        base_qs = base_qs.filter(amount__gte=filters["min_amount"])
    if filters.get("max_amount"):
        base_qs = base_qs.filter(amount__lte=filters["max_amount"])

    return base_qs

    
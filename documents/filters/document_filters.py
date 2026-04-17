from django.db.models import IntegerField, Value, F, ExpressionWrapper, Case, When, CharField
from django.db.models.functions import StrIndex, Substr, Cast
from documents.selectors.document_selector import DocumentSelector

_VALID_SORTS = {'name', 'total', 'date', 'invoice_number'}
_VALID_ORDERS = {'asc', 'desc'}


def apply_ordering(qs, sort, order):
    if sort not in _VALID_SORTS:
        sort = 'date'
    if order not in _VALID_ORDERS:
        order = 'desc'

    direction = '' if order == 'asc' else '-'

    if sort == 'name':
        return qs.order_by(f'{direction}original_name')
    elif sort == 'total':
        return qs.order_by(f'{direction}total_amount')
    elif sort == 'date':
        return qs.order_by(f'{direction}issue_date')
    elif sort == 'invoice_number':
        # Ordenación natural: prefijo alfabético + sufijo numérico (ej: FAC2026/1, FAC2026/2, FAC2026/10)
        qs = qs.annotate(
            _slash_pos=StrIndex('document_number', Value('/'))
        ).annotate(
            _inv_prefix=Case(
                When(
                    _slash_pos__gt=0,
                    then=Substr(
                        'document_number',
                        Value(1),
                        ExpressionWrapper(F('_slash_pos') - Value(1), output_field=IntegerField()),
                    )
                ),
                default=F('document_number'),
                output_field=CharField(),
            ),
            _inv_num=Case(
                When(
                    _slash_pos__gt=0,
                    then=Cast(
                        Substr(
                            'document_number',
                            ExpressionWrapper(F('_slash_pos') + Value(1), output_field=IntegerField()),
                        ),
                        output_field=IntegerField(),
                    )
                ),
                default=Value(0),
                output_field=IntegerField(),
            ),
        )
        return qs.order_by(f'{direction}_inv_prefix', f'{direction}_inv_num')

    return qs.order_by(f'{direction}issue_date')


def get_filtered_documents(request, base_qs=None):
    filters = {
        "doc_status": request.GET.get("doc_status"),
        "query": request.GET.get("q"),
        "company": request.GET.get("company"),
        "status": request.GET.get("status"),
        "review_level": request.GET.get("review_level"),
        "date_from": request.GET.get("date_from"),
        "date_to": request.GET.get("date_to"),
        "document_type": request.GET.get("document_type"),
        "flow": request.GET.get("flow"),
    }

    filters = {k: v for k, v in filters.items() if v}

    sort = request.GET.get("sort", "date")
    order = request.GET.get("order", "desc")

    client = request.user.client

    if base_qs is None:
        base_qs = DocumentSelector.for_client(client)

    qs = DocumentSelector.filtered(client, filters, base_qs=base_qs)
    return apply_ordering(qs, sort, order)


def get_exportable_documents(base_qs=None):
    if base_qs is None:
        raise ValueError("base_qs is required")
    else: 
        qs = base_qs.filter(
            is_archived=False,
            status="approved",
            document_type__in=["invoice", "corrected_invoice"],
        )

    return qs
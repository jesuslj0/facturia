from documents.selectors.document_selector import DocumentSelector

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

    client = request.user.client

    if base_qs is None:
        base_qs = DocumentSelector.for_client(client)

    return DocumentSelector.filtered(client, filters, base_qs=base_qs)
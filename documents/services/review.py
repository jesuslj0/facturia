"""Política de revisión a partir de la confianza de la extracción."""


def get_review_level(confidence: dict, document_type):
    extraction_confidence = confidence.get("confianza_extraccion", 0.0)
    fecha_conf = confidence.get("fecha", 0.0)
    total_conf = confidence.get("total", 0)

    if extraction_confidence >= 0.9:
        return "auto"

    if extraction_confidence < 0.75:
        return "required"

    if fecha_conf < 0.7 or total_conf < 0.8:
        return "required"

    if document_type.lower() not in ["invoice", "delivery"]:
        return "required"

    return "recommended"


def get_status(review_level):
    return "approved" if review_level == "auto" else "pending"

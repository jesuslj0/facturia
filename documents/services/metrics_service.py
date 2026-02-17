from django.db.models import Count, Sum
from ..models import Document


class MetricsService:

    @staticmethod
    def get_user_metrics(user):
        queryset = Document.objects.filter(
            client__clientuser__user=user
        )

        total = queryset.count()
        approved = queryset.filter(status="approved").count()
        rejected = queryset.filter(status="rejected").count()
        pending = queryset.filter(status="pending").count()

        total_amount = queryset.filter(
            status="approved"
        ).aggregate(total=Sum("total_amount"))["total"] or 0

        approval_rate = (approved / total * 100) if total > 0 else 0

        manual_review_count = queryset.filter(review_level="manual").count()

        return {
            "total_documents": total,
            "approved_documents": approved,
            "rejected_documents": rejected,
            "pending_documents": pending,
            "total_amount": total_amount,
            "approval_rate": approval_rate,
            "manual_review_count": manual_review_count,
        }

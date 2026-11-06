"""Public marketing endpoints — coupon validation for the checkout page."""
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from exams.models import Course

from .serializers import CouponValidateRequestSerializer
from .services import validate_coupon, CouponError


class ValidateCouponView(APIView):
    """Validate a coupon for a course and return the discounted quote.

    Used by the course checkout UI so the learner sees the final price before
    paying. The amount is always re-validated server-side at order creation.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        tenant = getattr(request, 'tenant', None)
        if tenant is None:
            return Response({'detail': 'Tenant required.'}, status=403)

        payload = CouponValidateRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        course = Course.objects.filter(
            id=payload.validated_data['course'], tenant=tenant
        ).first()
        if course is None:
            return Response({'detail': 'Course not found.'}, status=404)
        if course.is_hidden:
            return Response({'detail': 'Course not found.'}, status=404)

        student = getattr(request.user, 'profile', None)
        try:
            quote = validate_coupon(
                tenant, payload.validated_data['code'], course, student
            )
        except CouponError as exc:
            return Response({'valid': False, 'detail': exc.message}, status=400)

        return Response({
            'valid': True,
            'code': quote['code'],
            'discount_type': quote['discount_type'],
            'discount_value': quote['discount_value'],
            'original_amount': quote['original_amount'],
            'discount_amount': quote['discount_amount'],
            'final_amount': quote['final_amount'],
            'currency': quote['currency'],
        })

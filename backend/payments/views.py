"""Payment API — create order, verify a return, and receive provider webhooks.

Flow (paid course, pay-to-enrol mode):
  1. ``POST /payments/orders/``            → create a provider order + checkout params
  2. ``POST /payments/orders/<id>/verify/`` → verify the browser return, grant enrolment
  3. ``POST /payments/webhook/<provider>/`` → authoritative confirmation (no auth/tenant)
"""
import logging
import uuid

from django.conf import settings
from django.shortcuts import redirect
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from exams.models import Course
from users.models import CourseEnrollment

from .models import PaymentOrder
from .providers import get_client, PaymentError
from .serializers import PaymentOrderSerializer
from .services import mark_order_paid

logger = logging.getLogger(__name__)


def _active_gateway(tenant):
    gateway = tenant.active_payment_gateway
    if gateway and gateway.is_configured:
        return gateway
    return None


class CreateOrderView(APIView):
    """Create a payment order for a paid course in pay-to-enrol mode."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        tenant = getattr(request, 'tenant', None)
        if tenant is None:
            return Response({'detail': 'Tenant required.'}, status=403)

        student = getattr(request.user, 'profile', None)
        if student is None:
            return Response({'detail': 'Only students can enrol.'}, status=403)

        course_id = request.data.get('course')
        course = Course.objects.filter(id=course_id, tenant=tenant).first()
        if course is None:
            return Response({'detail': 'Course not found.'}, status=404)
        if course.is_hidden:
            return Response(
                {'detail': 'This course is not open for enrollment.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Already enrolled? Nothing to pay for.
        existing = CourseEnrollment.objects.filter(student=student, course=course).first()
        if existing and existing.status == 'approved':
            return Response({'detail': 'You are already enrolled.'}, status=400)

        if tenant.enroll_mode_for(course) != 'payment':
            return Response(
                {'detail': 'This course does not require payment to enrol.'},
                status=400,
            )

        gateway = _active_gateway(tenant)
        if gateway is None:
            return Response({'detail': 'No active payment gateway.'}, status=400)

        # --- Optional coupon: validate server-side and compute the charge. ---
        coupon = None
        charge_amount = course.price
        original_amount = course.price
        discount_amount = 0
        coupon_code = (request.data.get('coupon_code') or '').strip()
        if coupon_code:
            from marketing.services import validate_coupon, CouponError
            try:
                quote = validate_coupon(tenant, coupon_code, course, student)
            except CouponError as exc:
                return Response({'detail': exc.message}, status=400)
            coupon = quote['coupon']
            charge_amount = quote['final_amount']
            original_amount = quote['original_amount']
            discount_amount = quote['discount_amount']

        # A fully-discounted course needs no gateway round-trip: grant access now.
        if charge_amount <= 0:
            free_order = PaymentOrder.objects.create(
                tenant=tenant, student=student, course=course,
                provider=gateway.provider, provider_order_id=f'coupon-{uuid.uuid4().hex[:16]}',
                amount=0, currency=course.currency, is_test_mode=gateway.is_test_mode,
                coupon=coupon, original_amount=original_amount,
                discount_amount=discount_amount,
            )
            mark_order_paid(free_order)
            return Response(
                {
                    'order': PaymentOrderSerializer(free_order).data,
                    'checkout': None,
                    'free': True,
                    'enrolled': True,
                },
                status=status.HTTP_201_CREATED,
            )

        client = get_client(gateway)
        user = request.user
        # Provider order ids must be unique; a fresh PaymentOrder id works as the
        # receipt/order_id for both providers.
        pending = PaymentOrder(
            tenant=tenant, student=student, course=course,
            provider=gateway.provider, amount=charge_amount,
            currency=course.currency, is_test_mode=gateway.is_test_mode,
            coupon=coupon, original_amount=original_amount,
            discount_amount=discount_amount,
        )
        receipt = str(pending.id)
        # Where redirect-style providers (PayU) send the learner afterwards, and
        # the absolute callback URL PayU posts its signed result to.
        return_url = request.data.get('return_url') or ''
        callback_url = request.build_absolute_uri('/api/v1/payments/payu/callback/')
        try:
            result = client.create_order(
                amount=charge_amount,
                currency=course.currency,
                receipt=receipt,
                notes={'note': f'Enrolment: {course.name}'[:200], 'course_id': str(course.id)},
                customer={
                    'id': str(student.id),
                    'name': getattr(user, 'full_name', '') or user.email,
                    'email': user.email,
                    'phone': getattr(user, 'phone', '') or '',
                },
                return_url=return_url,
                callback_url=callback_url,
            )
        except PaymentError as exc:
            logger.warning('Payment order creation failed: %s', exc)
            return Response({'detail': 'Could not start payment. Try again later.'}, status=502)

        pending.provider_order_id = result['provider_order_id']
        pending.save()

        return Response(
            {
                'order': PaymentOrderSerializer(pending).data,
                'checkout': result['checkout'],
            },
            status=status.HTTP_201_CREATED,
        )


class VerifyOrderView(APIView):
    """Verify the browser return payload and grant enrolment on success."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        tenant = getattr(request, 'tenant', None)
        student = getattr(request.user, 'profile', None)
        order = PaymentOrder.objects.filter(
            id=pk, tenant=tenant, student=student
        ).select_related('course').first()
        if order is None:
            return Response({'detail': 'Order not found.'}, status=404)

        if order.is_paid:
            return Response({'status': 'paid', 'enrolled': True})

        gateway = _active_gateway(tenant)
        if gateway is None:
            return Response({'detail': 'No active payment gateway.'}, status=400)

        client = get_client(gateway)
        payload = dict(request.data)
        payload.setdefault('order_id', order.provider_order_id)
        try:
            ok, payment_id = client.verify_return(payload)
        except PaymentError as exc:
            logger.warning('Payment verification failed: %s', exc)
            return Response({'detail': 'Verification failed. Please try again.'}, status=502)

        if not ok:
            return Response({'status': 'pending', 'enrolled': False}, status=202)

        mark_order_paid(order, provider_payment_id=payment_id)
        return Response({'status': 'paid', 'enrolled': True})


@method_decorator(csrf_exempt, name='dispatch')
class WebhookView(APIView):
    """Provider webhook receiver. No auth/tenant header — resolved from the order."""
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request, provider):
        raw_body = request.body
        if provider == 'razorpay':
            from .providers import RazorpayClient as _Cls
        elif provider == 'cashfree':
            from .providers import CashfreeClient as _Cls
        elif provider == 'payu':
            from .providers import PayUClient as _Cls
        else:
            return Response({'detail': 'Unknown provider.'}, status=404)

        order_id, payment_id, is_paid = _Cls.parse_webhook(raw_body)
        if not order_id:
            return Response({'detail': 'Ignored.'}, status=200)

        order = PaymentOrder.objects.filter(
            provider=provider, provider_order_id=order_id
        ).select_related('tenant').first()
        if order is None:
            # Unknown order — ack so the provider stops retrying.
            return Response({'detail': 'Ignored.'}, status=200)

        gateway = _active_gateway(order.tenant)
        if gateway is None:
            return Response({'detail': 'Ignored.'}, status=200)

        client = get_client(gateway)
        if not client.verify_webhook(raw_body, request.headers):
            return Response({'detail': 'Invalid signature.'}, status=400)

        if is_paid:
            mark_order_paid(order, provider_payment_id=payment_id)
        return Response({'detail': 'ok'}, status=200)


@method_decorator(csrf_exempt, name='dispatch')
class PayUCallbackView(APIView):
    """PayU surl/furl target — a signed browser POST after the hosted checkout.

    PayU redirects the learner's browser here (form POST). We verify the signed
    payload, grant enrolment on success, then 302-redirect back into the app
    (the ``return_url`` we passed as ``udf1``, which is inside PayU's hash and so
    cannot be tampered with).
    """
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def _handle(self, request):
        params = {k: v for k, v in request.POST.items()} or dict(request.GET.items())
        txnid = params.get('txnid')
        fallback = params.get('udf1') or getattr(settings, 'FRONTEND_URL', '') or '/'

        if not txnid:
            return redirect(_with_status(fallback, 'failed'))

        order = PaymentOrder.objects.filter(
            provider='payu', provider_order_id=txnid
        ).select_related('tenant').first()
        if order is None:
            return redirect(_with_status(fallback, 'failed'))

        gateway = _active_gateway(order.tenant)
        return_url = params.get('udf1') or fallback
        if gateway is None:
            return redirect(_with_status(return_url, 'failed'))

        client = get_client(gateway)
        try:
            ok, payment_id = client.verify_return(params)
        except PaymentError as exc:
            logger.warning('PayU verification failed: %s', exc)
            ok, payment_id = False, ''

        if ok:
            mark_order_paid(order, provider_payment_id=payment_id)
            return redirect(_with_status(return_url, 'success'))
        return redirect(_with_status(return_url, 'failed'))

    def post(self, request):
        return self._handle(request)

    def get(self, request):
        return self._handle(request)


def _with_status(url, status_value):
    """Append ``payment=<status>`` to a return URL, preserving existing query."""
    if not url:
        url = '/'
    sep = '&' if '?' in url else '?'
    return f'{url}{sep}payment={status_value}'

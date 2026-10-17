from datetime import date, datetime, timedelta, timezone as datetime_timezone
from decimal import Decimal
from unittest.mock import patch

from directory.models import Item, ItemType
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from transactions.models import Transaction

from .forms import ReportDateRangeForm
from .models import Report


class ReportDateRangeFormTests(TestCase):
    def test_default_range_is_last_three_days_including_today(self):
        today = timezone.localdate()

        form = ReportDateRangeForm()

        self.assertEqual(form.initial['date_from'], today - timedelta(days=2))
        self.assertEqual(form.initial['date_to'], today)

    def test_end_date_cannot_precede_start_date(self):
        form = ReportDateRangeForm({
            'date_from': '2025-01-02',
            'date_to': '2025-01-01',
        })

        self.assertFalse(form.is_valid())
        self.assertIn('date_to', form.errors)


class CashReportDateRangeTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username='reporter',
            password='test-password',
        )
        permission = Permission.objects.get(
            content_type__app_label='reports',
            codename='add_report',
        )
        self.user.user_permissions.add(permission)

        product_type = ItemType.objects.create(
            name='Товары',
            handle='product',
            order_number=1,
        )
        self.product = Item.objects.create(
            item_type=product_type,
            name='Тестовый товар',
            handle='test-product',
            order_number=1,
        )

        Transaction.objects.create(
            item=self.product,
            price=Decimal('10.00'),
            quantity=2,
            cashier=self.user,
            created_at=timezone.make_aware(datetime(2025, 1, 2, 12)),
        )
        Transaction.objects.create(
            item=self.product,
            price=Decimal('10.00'),
            quantity=3,
            cashier=self.user,
            created_at=timezone.make_aware(datetime(2025, 1, 1, 12)),
        )
        self.client.force_login(self.user)
        self.generate_url = reverse(
            'reports:generate_report',
            kwargs={'handle_key': 'cash-report'},
        )

    def test_report_filters_transactions_and_saves_selected_period(self):
        date_range = {'date_from': '2025-01-02', 'date_to': '2025-01-02'}

        response = self.client.get(self.generate_url, date_range)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context_data['product_data'], Decimal('20.00'))
        self.assertEqual(response.context_data['date_from'], date(2025, 1, 2))
        self.assertEqual(response.context_data['date_to'], date(2025, 1, 2))

        response = self.client.post(self.generate_url, date_range)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('reports:report_list'))
        report = Report.objects.get()
        self.assertIn('02.01.2025', report.name)
        self.assertIn('02.01.2025', report.dump)

    def test_date_picker_uses_application_timezone_today(self):
        utc_now = datetime(2025, 1, 1, 18, tzinfo=datetime_timezone.utc)
        with timezone.override('Asia/Novokuznetsk'), patch(
            'django.utils.timezone.now',
            return_value=utc_now,
        ):
            response = self.client.get(self.generate_url)

        self.assertEqual(
            response.context_data['application_today'],
            date(2025, 1, 2),
        )
        self.assertContains(response, 'data-application-today="2025-01-02"')

# Create your tests here.

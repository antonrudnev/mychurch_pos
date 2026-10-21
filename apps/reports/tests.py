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
from .models import Report, ReportType
from .views import render_cash_report_document


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

    def test_cash_report_pdf_opens_inline_with_selected_date_range(self):
        date_range = {'date_from': '2025-01-02', 'date_to': '2025-01-02'}
        report_response = self.client.get(self.generate_url, date_range)
        pdf_response = self.client.get(reverse('reports:cash_report_pdf'), date_range)

        self.assertEqual(pdf_response.status_code, 200)
        self.assertEqual(pdf_response['Content-Type'], 'application/pdf')
        self.assertTrue(pdf_response['Content-Disposition'].startswith('inline;'))
        self.assertTrue(pdf_response.content.startswith(b'%PDF-'))
        self.assertContains(
            report_response,
            f'href="{reverse("reports:cash_report_pdf")}?date_from=2025-01-02&amp;date_to=2025-01-02"',
        )
        self.assertContains(report_response, 'target="_blank"')

    def test_cash_report_pdf_rejects_invalid_date_range(self):
        response = self.client.get(
            reverse('reports:cash_report_pdf'),
            {'date_from': 'not-a-date', 'date_to': '2025-01-02'},
        )

        self.assertEqual(response.status_code, 400)
        self.assertNotEqual(response['Content-Type'], 'application/pdf')

    def test_cash_report_table_font_scales_to_fit_one_a4_page(self):
        treby_type = ItemType.objects.create(
            name='Требы для проверки печати',
            handle='treby-print-fit',
            order_number=2,
        )
        for index in range(80):
            Item.objects.create(
                item_type=treby_type,
                name=f'Позиция для проверки печати {index}',
                handle=f'treby-print-fit-{index}',
                order_number=index + 1,
            )

        response = self.client.get(
            self.generate_url,
            {'date_from': '2025-01-02', 'date_to': '2025-01-02'},
        )
        document, font_size = render_cash_report_document(
            response.content.decode(response.charset),
            base_url='http://testserver/',
        )

        self.assertEqual(len(document.pages), 1)
        self.assertLess(font_size, 12)

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

    def test_staff_data_displays_transaction_totals(self):
        staff_type = ItemType.objects.create(
            name='Содержание причта',
            handle='staff-clergy',
            order_number=2,
        )
        staff_item = Item.objects.create(
            item_type=staff_type,
            name='Священник',
            handle='staff-clergy-priest',
            order_number=1,
        )
        Transaction.objects.create(
            item=staff_item,
            price=Decimal('25.50'),
            quantity=2,
            cashier=self.user,
            created_at=timezone.make_aware(datetime(2025, 1, 2, 12)),
        )

        response = self.client.get(
            self.generate_url,
            {'date_from': '2025-01-02', 'date_to': '2025-01-02'},
        )

        self.assertEqual(response.status_code, 200)
        staff_row = next(
            row for row in response.context_data['staff_data']
            if row['short_handle'] == 'staff-clergy'
        )
        self.assertEqual(staff_row['total_cost'], Decimal('51'))
        self.assertContains(response, '51')


class ReportManagementTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='manager',
            password='test-password',
        )
        view_permission = Permission.objects.get(
            content_type__app_label='reports',
            codename='view_report',
        )
        self.user.user_permissions.add(view_permission)
        self.report_type, _created = ReportType.objects.get_or_create(
            handle='cash-report',
            defaults={'name': 'Кассовый отчет'},
        )
        self.report = Report.objects.create(
            name='Исходное название',
            report_type=self.report_type,
            dump='<p>Отчет</p>',
        )
        self.manage_url = reverse(
            'reports:manage_report',
            kwargs={'report_id': self.report.id},
        )
        self.client.force_login(self.user)

    def grant_permission(self, codename):
        permission = Permission.objects.get(
            content_type__app_label='reports',
            codename=codename,
        )
        self.user.user_permissions.add(permission)

    def test_user_without_management_permissions_sees_plain_report_name(self):
        response = self.client.get(reverse('reports:report_list'))

        self.assertContains(response, 'Исходное название')
        self.assertNotContains(response, f'href="{self.manage_url}"')
        self.assertEqual(self.client.get(self.manage_url).status_code, 403)

    def test_change_permission_allows_renaming_but_not_deleting(self):
        self.grant_permission('change_report')

        response = self.client.get(self.manage_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Сохранить название')
        self.assertNotContains(response, 'Удалить отчет')

        response = self.client.post(
            self.manage_url,
            {'action': 'rename', 'name': 'Новое название'},
        )
        self.assertRedirects(response, reverse('reports:report_list'))
        self.report.refresh_from_db()
        self.assertEqual(self.report.name, 'Новое название')

        response = self.client.post(self.manage_url, {'action': 'delete'})
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Report.objects.filter(pk=self.report.pk).exists())

    def test_delete_permission_allows_deletion_but_not_renaming(self):
        self.grant_permission('delete_report')

        response = self.client.get(self.manage_url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Сохранить название')
        self.assertContains(response, 'Удалить отчет')

        response = self.client.post(
            self.manage_url,
            {'action': 'rename', 'name': 'Новое название'},
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Report.objects.filter(pk=self.report.pk).exists())

        response = self.client.post(self.manage_url, {'action': 'delete'})
        self.assertRedirects(response, reverse('reports:report_list'))
        self.assertFalse(Report.objects.filter(pk=self.report.pk).exists())

    def test_report_title_and_open_link_have_distinct_destinations(self):
        self.grant_permission('change_report')

        response = self.client.get(reverse('reports:home'))

        self.assertContains(
            response,
            f'href="{self.manage_url}"',
        )
        self.assertContains(
            response,
            f'href="{reverse("reports:print_report", args=[self.report.id])}"',
        )
        self.assertContains(
            response,
            f'href="{reverse("reports:print_report", args=[self.report.id])}?format=pdf"',
        )

    def test_print_report_pdf_format_uses_cash_report_pdf_renderer(self):
        response = self.client.get(
            reverse('reports:print_report', args=[self.report.id]),
            {'format': 'pdf'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response['Content-Disposition'].startswith('inline;'))
        self.assertTrue(response.content.startswith(b'%PDF-'))

# Create your tests here.

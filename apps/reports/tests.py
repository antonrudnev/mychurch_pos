from datetime import date, datetime, timedelta, timezone as datetime_timezone
from decimal import Decimal
from unittest.mock import patch

from directory.models import Item, ItemType
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.http import content_disposition_header
from transactions.models import Transaction

from .forms import ReportDateRangeForm
from .models import Report, ReportType
from .views import render_report_document


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
            is_product_group=True,
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
        Transaction.objects.filter(
            created_at__date=date(2025, 1, 2),
        ).update(is_verified=True)

        response = self.client.get(self.generate_url, date_range)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context_data['product_total'], Decimal('20.00'))
        self.assertEqual(response.context_data['date_from'], date(2025, 1, 2))
        self.assertEqual(response.context_data['date_to'], date(2025, 1, 2))

        response = self.client.post(self.generate_url, date_range)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('reports:home'))
        report = Report.objects.get()
        self.assertIn('02.01.2025', report.name)
        self.assertIn('02.01.2025', report.dump)

    def test_report_period_submission_redirects_to_unverified_transactions(self):
        response = self.client.get(
            self.generate_url,
            {'date_from': '2025-01-02', 'date_to': '2025-01-02'},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            f"{reverse('transactions:transaction_list')}?unverified=1&date_from=2025-01-02&date_to=2025-01-02&preset=custom&report_handle=cash-report",
        )
        self.assertFalse(Report.objects.exists())

    def test_saving_report_does_not_prompt_again_for_unverified_transactions(self):
        response = self.client.post(
            self.generate_url,
            {'date_from': '2025-01-02', 'date_to': '2025-01-02'},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('reports:home'))
        self.assertTrue(Report.objects.exists())

    def test_report_period_without_unverified_transactions_opens_preview(self):
        Transaction.objects.filter(created_at__date=date(2025, 1, 2)).update(
            is_verified=True,
        )

        response = self.client.get(
            self.generate_url,
            {'date_from': '2025-01-02', 'date_to': '2025-01-02'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('product_total', response.context)
        self.assertFalse(Report.objects.exists())

    def test_report_period_can_proceed_without_verifying_transactions(self):
        permission = Permission.objects.get(
            content_type__app_label='transactions',
            codename='verify_transaction',
        )
        self.user.user_permissions.add(permission)
        response = self.client.get(
            self.generate_url,
            {
                'date_from': '2025-01-02',
                'date_to': '2025-01-02',
                'skip_unverified_check': '1',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('product_total', response.context)
        self.assertFalse(Report.objects.exists())

    def test_report_period_cannot_skip_unverified_check_without_verify_permission(self):
        response = self.client.get(
            self.generate_url,
            {
                'date_from': '2025-01-02',
                'date_to': '2025-01-02',
                'skip_unverified_check': '1',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('transactions:transaction_list'), response.url)
        self.assertFalse(Report.objects.exists())

    def test_return_from_transaction_review_opens_report_date_picker(self):
        response = self.client.get(
            self.generate_url,
            {
                'select_period': '1',
                'preserve_dates': '1',
                'preset': 'last-week',
                'date_from': '2025-01-02',
                'date_to': '2025-01-03',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context['form'].initial['date_from'],
            date(2025, 1, 2),
        )
        self.assertEqual(
            response.context['form'].initial['date_to'],
            date(2025, 1, 3),
        )
        self.assertEqual(response.context['selected_preset'], 'last-week')
        self.assertTrue(response.context['preserve_date_values'])
        self.assertContains(response, 'value="last-week" selected')
        self.assertContains(response, 'id="id_date_from"')
        self.assertContains(response, 'id="id_date_to"')
        self.assertContains(response, 'value="2025-01-02"')
        self.assertContains(response, 'value="2025-01-03"')

        submit_response = self.client.get(
            self.generate_url,
            {
                'preset': 'last-week',
                'date_from': '2025-01-02',
                'date_to': '2025-01-03',
            },
        )
        self.assertRedirects(
            submit_response,
            f"{reverse('transactions:transaction_list')}?unverified=1&date_from=2025-01-02&date_to=2025-01-03&preset=last-week&report_handle=cash-report",
            fetch_redirect_response=False,
        )

    def test_cash_report_pdf_opens_inline_with_selected_date_range(self):
        date_range = {'date_from': '2025-01-02', 'date_to': '2025-01-02'}
        Transaction.objects.filter(
            created_at__date=date(2025, 1, 2),
        ).update(is_verified=True)
        report_response = self.client.get(self.generate_url, date_range)
        pdf_response = self.client.get(reverse('reports:cash_report_pdf'), date_range)

        self.assertEqual(pdf_response.status_code, 200)
        self.assertEqual(pdf_response['Content-Type'], 'application/pdf')
        self.assertTrue(pdf_response['Content-Disposition'].startswith('inline;'))
        self.assertEqual(
            pdf_response['Content-Disposition'],
            'inline; filename="cas-report-2025-01-02-2025-01-02.pdf"',
        )
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

    def test_cash_report_renders_on_one_a4_page_at_fixed_font_size(self):
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
        document = render_report_document(
            response.content.decode(response.charset),
            base_url='http://testserver/',
        )

        self.assertEqual(len(document.pages), 1)

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
        self.assertContains(response, 'Кассовый отчет')
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


class ProductReportTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username='product-reporter',
            password='test-password',
        )
        permission = Permission.objects.get(
            content_type__app_label='reports',
            codename='add_report',
        )
        self.user.user_permissions.add(permission)

        product_type = ItemType.objects.create(
            name='Товарная группа',
            handle='product-group',
            is_product_group=True,
        )
        self.product = Item.objects.create(
            item_type=product_type,
            name='Тестовый товар',
            handle='product-report-test-item',
            price=Decimal('10.00'),
            is_active=False,
        )
        non_product_type = ItemType.objects.create(
            name='Услуги',
            handle='product-report-non-products',
        )
        self.non_product = Item.objects.create(
            item_type=non_product_type,
            name='Не товар',
            handle='product-report-non-product',
            price=Decimal('20.00'),
        )

        for price, quantity in (
            (Decimal('10.00'), 2),
            (Decimal('10.00'), 3),
            (Decimal('12.00'), 1),
        ):
            Transaction.objects.create(
                item=self.product,
                price=price,
                quantity=quantity,
                cashier=self.user,
                created_at=timezone.make_aware(datetime(2025, 1, 2, 12)),
                is_verified=True,
            )
        Transaction.objects.create(
            item=self.product,
            price=Decimal('99.00'),
            quantity=1,
            cashier=self.user,
            created_at=timezone.make_aware(datetime(2025, 1, 2, 12)),
            is_verified=True,
            is_deleted=True,
        )
        Transaction.objects.create(
            item=self.non_product,
            price=Decimal('20.00'),
            quantity=4,
            cashier=self.user,
            created_at=timezone.make_aware(datetime(2025, 1, 2, 12)),
            is_verified=True,
        )
        self.client.force_login(self.user)
        self.generate_url = reverse(
            'reports:generate_report',
            kwargs={'handle_key': 'product-report'},
        )
        self.date_range = {
            'date_from': '2025-01-02',
            'date_to': '2025-01-02',
        }

    def test_date_picker_displays_report_name(self):
        response = self.client.get(self.generate_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Товарная ведомость')

    def test_unverified_review_redirect_preserves_product_report_handle(self):
        Transaction.objects.create(
            item=self.product,
            price=Decimal('10.00'),
            quantity=1,
            cashier=self.user,
            created_at=timezone.make_aware(datetime(2025, 1, 2, 12)),
        )

        response = self.client.get(self.generate_url, self.date_range)

        self.assertEqual(
            response.url,
            f"{reverse('transactions:transaction_list')}?unverified=1&date_from=2025-01-02&date_to=2025-01-02&preset=custom&report_handle=product-report",
        )

    def test_report_groups_active_product_sales_by_name_and_transaction_price(self):
        response = self.client.get(self.generate_url, self.date_range)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context_data['overall_total_cost'], Decimal('62.00'))
        self.assertEqual(
            list(response.context_data['rows']),
            [
                {
                    'item__name': 'Тестовый товар',
                    'price': Decimal('10.00'),
                    'total_quantity': 5,
                    'total_cost': Decimal('50.00'),
                },
                {
                    'item__name': 'Тестовый товар',
                    'price': Decimal('12.00'),
                    'total_quantity': 1,
                    'total_cost': Decimal('12.00'),
                },
            ],
        )
        self.assertContains(response, 'Товарная ведомость за')
        self.assertContains(response, 'Количество')
        self.assertContains(response, 'Итого')
        self.assertContains(
            response,
            f'href="{reverse("reports:product_report_pdf")}?date_from=2025-01-02&amp;date_to=2025-01-02"',
        )

    def test_report_can_be_saved_and_rendered_as_pdf(self):
        response = self.client.post(self.generate_url, self.date_range)

        self.assertEqual(response.status_code, 302)
        report = Report.objects.get()
        self.assertEqual(report.name, 'Товарная ведомость за 02.01.2025')
        self.assertEqual(report.report_type.handle, 'product-report')
        self.assertIn('62', report.dump)
        self.assertIn('Тестовый товар', report.dump)

        pdf_response = self.client.get(
            reverse('reports:product_report_pdf'),
            self.date_range,
        )
        self.assertEqual(pdf_response.status_code, 200)
        self.assertEqual(pdf_response['Content-Type'], 'application/pdf')
        self.assertTrue(pdf_response.content.startswith(b'%PDF-'))


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

    def test_saved_report_print_pdf_returns_a_pdf(self):
        response = self.client.get(
            reverse('reports:print_report', args=[self.report.id]),
            {'format': 'pdf'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertEqual(
            response['Content-Disposition'],
            content_disposition_header(False, 'Исходное название.pdf'),
        )
        self.assertTrue(response.content.startswith(b'%PDF-'))

    def test_print_report_requires_view_permission(self):
        self.user.user_permissions.clear()

        response = self.client.get(
            reverse('reports:print_report', args=[self.report.id]),
        )

        self.assertEqual(response.status_code, 403)

# Create your tests here.

from datetime import date, datetime, timedelta
from decimal import Decimal

from directory.models import Item, ItemType
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from integrations.models import DocumentType, IncomingDocument

from .models import IncomingTransaction, Transaction


class TransactionViewsTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username='cashier',
            password='test-password',
        )
        self.other_user = user_model.objects.create_user(
            username='other-cashier',
            password='test-password',
        )
        self.item_type = ItemType.objects.create(
            name='Тестовая категория',
            handle='test-category',
            order_number=1,
        )
        self.item = Item.objects.create(
            item_type=self.item_type,
            name='Тестовая позиция',
            handle='test-item',
            price=Decimal('12.50'),
            order_number=1,
        )
        self.grant_permission(self.user, 'view_transaction')
        self.grant_permission(self.user, 'add_transaction')
        self.client.force_login(self.user)

    def grant_permission(self, user, codename):
        permission = Permission.objects.get(
            content_type__app_label='transactions',
            codename=codename,
        )
        user.user_permissions.add(permission)

    def grant_directory_permission(self, user, codename):
        permission = Permission.objects.get(
            content_type__app_label='directory',
            codename=codename,
        )
        user.user_permissions.add(permission)

    def create_transaction(self, cashier, item=None):
        return Transaction.objects.create(
            cashier=cashier,
            item=item or self.item,
            price=Decimal('12.50'),
            quantity=1,
        )

    def create_incoming_document(self):
        return IncomingDocument.objects.create(
            document_type=DocumentType.PRODUCT_REPORT,
            dropbox_file_id='incoming-test-file',
            original_name='Ведомость.xlsx',
            dropbox_path='/reports/Ведомость.xlsx',
            local_file='dropbox/Ведомость.xlsx',
        )

    def create_incoming_transaction(
        self,
        document,
        *,
        item=None,
        use_default_item=True,
        raw_name='Распознанная позиция',
        raw_counts=None,
        quantity=1,
        price=Decimal('12.50'),
        report_date=None,
        row_number=1,
    ):
        return IncomingTransaction.objects.create(
            document=document,
            item=self.item if use_default_item else item,
            raw_name=raw_name,
            raw_counts=[quantity] if raw_counts is None else raw_counts,
            quantity=quantity,
            price=price,
            report_date=report_date,
            row_number=row_number,
        )

    def test_home_page_shows_the_two_main_actions(self):
        response = self.client.get(reverse('transactions:home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Мои транзакции')
        self.assertContains(response, 'Создать транзакцию')
        self.assertContains(
            response,
            f'href="{reverse("transactions:transaction_list")}"',
        )
        self.assertContains(
            response,
            f'href="{reverse("transactions:item_type_select")}"',
        )

    def test_transaction_list_shows_only_current_users_transactions(self):
        own_transaction = self.create_transaction(self.user)
        other_transaction = self.create_transaction(self.other_user)

        response = self.client.get(reverse('transactions:transaction_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, str(own_transaction.item.name))
        self.assertNotContains(response, str(other_transaction.cashier.username))

    def test_user_with_view_all_permission_sees_other_cashiers_transactions(self):
        self.grant_permission(self.user, 'view_all_transactions')
        other_transaction = self.create_transaction(self.other_user)

        response = self.client.get(reverse('transactions:transaction_list'))

        self.assertContains(response, str(other_transaction.item.name))
        self.assertContains(response, str(self.other_user.username))

    def test_verification_review_lists_only_unverified_transactions_in_selected_period(self):
        self.grant_permission(self.user, 'verify_transaction')
        self.user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label='reports',
                codename='add_report',
            )
        )
        matching_transaction = self.create_transaction(self.user)
        matching_transaction.created_at = timezone.make_aware(datetime(2025, 1, 2, 12))
        matching_transaction.save(update_fields=['created_at'])

        verified_transaction = self.create_transaction(self.user)
        verified_transaction.created_at = timezone.make_aware(datetime(2025, 1, 2, 13))
        verified_transaction.is_verified = True
        verified_transaction.save(update_fields=['created_at', 'is_verified'])

        outside_range_transaction = self.create_transaction(self.other_user)
        outside_range_transaction.created_at = timezone.make_aware(
            datetime(2025, 1, 3, 12)
        )
        outside_range_transaction.save(update_fields=['created_at'])

        other_cashier_transaction = self.create_transaction(self.other_user)
        other_cashier_transaction.created_at = timezone.make_aware(
            datetime(2025, 1, 2, 14)
        )
        other_cashier_transaction.save(update_fields=['created_at'])

        response = self.client.get(
            reverse('transactions:transaction_list'),
            {
                'unverified': '1',
                'date_from': '2025-01-02',
                'date_to': '2025-01-02',
                'preset': 'last-week',
                'report_handle': 'product-report',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Проверьте эти транзакции')
        self.assertContains(response, other_cashier_transaction.cashier.username)
        listed_ids = {
            transaction.pk
            for transaction in response.context['transactions']
        }
        self.assertEqual(
            listed_ids,
            {matching_transaction.pk, other_cashier_transaction.pk},
        )
        self.assertEqual(response.context['paginator'].count, 2)
        self.assertContains(
            response,
            f'href="{reverse("transactions:transaction_manage", args=[matching_transaction.pk])}?unverified=1&amp;date_from=2025-01-02&amp;date_to=2025-01-02&amp;preset=last-week&amp;report_handle=product-report&amp;page=1"',
        )
        self.assertContains(
            response,
            'select_period=1&amp;preserve_dates=1&amp;preset=last-week&amp;date_from=2025-01-02&amp;date_to=2025-01-02&amp;report_handle=product-report',
        )
        self.assertContains(
            response,
            f'href="{reverse("reports:generate_report", args=["product-report"])}?date_from=2025-01-02&amp;date_to=2025-01-02&amp;preset=last-week&amp;skip_unverified_check=1&amp;report_handle=product-report"',
        )
        self.assertContains(response, 'Продолжить без проверки')

        manage_response = self.client.get(
            reverse(
                'transactions:transaction_manage',
                args=[matching_transaction.pk],
            ),
            {
                'unverified': '1',
                'date_from': '2025-01-02',
                'date_to': '2025-01-02',
                'preset': 'last-week',
                'report_handle': 'product-report',
                'page': '1',
            },
        )
        self.assertContains(
            manage_response,
            f'href="{reverse("transactions:transaction_list")}?unverified=1&amp;date_from=2025-01-02&amp;date_to=2025-01-02&amp;preset=last-week&amp;report_handle=product-report&amp;page=1"',
        )
    def test_verification_review_requires_verify_permission_and_valid_dates(self):
        url = reverse('transactions:transaction_list')
        query = {'unverified': '1', 'date_from': '2025-01-02', 'date_to': '2025-01-02'}

        response = self.client.get(url, query)

        self.assertEqual(response.status_code, 403)

        self.grant_permission(self.user, 'verify_transaction')
        response = self.client.get(
            url,
            {'unverified': '1', 'date_from': 'invalid', 'date_to': '2025-01-02'},
        )

        self.assertEqual(response.status_code, 400)

    def test_report_creator_can_review_and_edit_own_unverified_transactions(self):
        reports_permission = Permission.objects.get(
            content_type__app_label='reports',
            codename='add_report',
        )
        self.user.user_permissions.add(reports_permission)
        self.grant_permission(self.user, 'change_transaction')
        self.user.user_permissions.remove(
            Permission.objects.get(
                content_type__app_label='transactions',
                codename='view_transaction',
            )
        )
        own_transaction = self.create_transaction(self.user)
        own_transaction.created_at = timezone.make_aware(datetime(2025, 1, 2, 12))
        own_transaction.save(update_fields=['created_at'])
        other_transaction = self.create_transaction(self.other_user)
        other_transaction.created_at = timezone.make_aware(datetime(2025, 1, 2, 13))
        other_transaction.save(update_fields=['created_at'])

        response = self.client.get(
            reverse('transactions:transaction_list'),
            {
                'unverified': '1',
                'date_from': '2025-01-02',
                'date_to': '2025-01-02',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'href="{reverse("transactions:transaction_manage", args=[own_transaction.pk])}?unverified=1&amp;date_from=2025-01-02&amp;date_to=2025-01-02&amp;preset=custom&amp;report_handle=cash-report&amp;page=1"',
        )
        self.assertNotContains(response, str(other_transaction.cashier.username))
        self.assertNotContains(response, 'Продолжить без проверки')

        self.grant_permission(self.user, 'view_all_transactions')
        all_transactions_response = self.client.get(
            reverse('transactions:transaction_list'),
            {
                'unverified': '1',
                'date_from': '2025-01-02',
                'date_to': '2025-01-02',
            },
        )
        self.assertContains(
            all_transactions_response,
            str(other_transaction.cashier.username),
        )

        manage_response = self.client.get(
            reverse('transactions:transaction_manage', args=[own_transaction.pk]),
            {
                'unverified': '1',
                'date_from': '2025-01-02',
                'date_to': '2025-01-02',
            },
        )
        self.assertEqual(manage_response.status_code, 200)
        self.assertTrue(manage_response.context['can_change_transaction'])

    def test_transaction_name_links_to_manage_page_when_user_can_change(self):
        self.grant_permission(self.user, 'change_transaction')
        transaction = self.create_transaction(self.user)

        response = self.client.get(reverse('transactions:transaction_list'))

        self.assertContains(
            response,
            f'href="{reverse("transactions:transaction_manage", args=[transaction.id])}"',
        )

    def test_manage_page_shows_transaction_details_and_editable_fields(self):
        self.grant_permission(self.user, 'change_transaction')
        transaction = self.create_transaction(self.user)

        response = self.client.get(
            reverse('transactions:transaction_manage', args=[transaction.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.item.name)
        self.assertContains(response, self.item_type.name)
        self.assertContains(response, 'name="price"')
        self.assertContains(response, 'name="quantity"')
        self.assertNotContains(response, 'name="item"')
        self.assertNotContains(response, 'name="cashier"')

    def test_manage_page_shows_transaction_data_as_labels_without_change_permission(self):
        transaction = self.create_transaction(self.user)

        response = self.client.get(
            reverse('transactions:transaction_manage', args=[transaction.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Сумма')
        self.assertRegex(response.content.decode(), r'12[.,]50')
        self.assertContains(response, 'Количество')
        self.assertContains(response, '<div class="form-control-plaintext fw-bold">1</div>')
        self.assertNotContains(response, 'name="action" value="save"')
        self.assertNotContains(response, 'name="price"')
        self.assertNotContains(response, 'name="quantity"')

    def test_view_only_user_can_open_transaction_from_list(self):
        transaction = self.create_transaction(self.user)

        response = self.client.get(reverse('transactions:transaction_list'))

        self.assertContains(
            response,
            f'href="{reverse("transactions:transaction_manage", args=[transaction.id])}"',
        )

    def test_manage_page_edits_price_and_quantity_with_change_permission(self):
        self.grant_permission(self.user, 'change_transaction')
        transaction = self.create_transaction(self.user)

        response = self.client.post(
            reverse('transactions:transaction_manage', args=[transaction.id]),
            {'action': 'save', 'price': '20.75', 'quantity': '4'},
        )

        self.assertRedirects(response, reverse('transactions:transaction_list'))
        transaction.refresh_from_db()
        self.assertEqual(transaction.price, Decimal('20.75'))
        self.assertEqual(transaction.quantity, 4)

    def test_manage_page_edits_bank_receipt_datetime_with_change_permission(self):
        self.grant_permission(self.user, 'change_transaction')
        bank_receipt = Item.objects.get(handle='bank-receipt')
        transaction = self.create_transaction(self.user, item=bank_receipt)
        transaction.created_at = timezone.make_aware(datetime(2025, 1, 2, 12, 30))
        transaction.save(update_fields=['created_at'])
        manage_url = reverse(
            'transactions:transaction_manage',
            args=[transaction.pk],
        )

        response = self.client.get(manage_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="created-at-display"')
        self.assertContains(response, 'id="created-at-editor" class="text-end" hidden')
        self.assertContains(response, 'type="datetime-local"')
        self.assertContains(response, 'lang="ru"')
        self.assertContains(response, 'name="created_at"')
        self.assertContains(response, 'value="2025-01-02T12:30"')
        self.assertContains(response, 'name="action" value="save"')
        self.assertNotContains(response, 'name="action" value="save_created_at"')

        response = self.client.post(
            manage_url,
            {
                'action': 'save',
                'created_at': '2025-02-03T14:45',
                'price': '12.50',
                'quantity': '1',
            },
        )

        self.assertRedirects(response, reverse('transactions:transaction_list'))
        transaction.refresh_from_db()
        self.assertEqual(
            timezone.localtime(transaction.created_at),
            timezone.make_aware(datetime(2025, 2, 3, 14, 45)),
        )

    def test_bank_receipt_datetime_edit_requires_change_permission(self):
        bank_receipt = Item.objects.get(handle='bank-receipt')
        transaction = self.create_transaction(self.user, item=bank_receipt)
        manage_url = reverse(
            'transactions:transaction_manage',
            args=[transaction.pk],
        )

        response = self.client.get(manage_url)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="created-at-display"')
        self.assertNotContains(response, 'name="created_at"')

        response = self.client.post(
            manage_url,
            {
                'action': 'save',
                'created_at': '2025-02-03T14:45',
                'price': '12.50',
                'quantity': '1',
            },
        )

        self.assertEqual(response.status_code, 403)

    def test_list_links_keep_the_current_page_when_opening_a_transaction(self):
        transaction = self.create_transaction(self.user)
        transaction.created_at = timezone.now() - timedelta(days=1)
        transaction.save(update_fields=['created_at'])
        for _ in range(5):
            self.create_transaction(self.user)

        response = self.client.get(
            reverse('transactions:transaction_list'),
            {'page': 2},
        )

        self.assertContains(
            response,
            f'href="{reverse("transactions:transaction_manage", args=[transaction.id])}?page=2"',
        )

    def test_manage_return_link_keeps_the_transaction_list_page(self):
        transaction = self.create_transaction(self.user)

        response = self.client.get(
            f'{reverse("transactions:transaction_manage", args=[transaction.id])}?page=2'
        )

        self.assertContains(
            response,
            f'href="{reverse("transactions:transaction_list")}?page=2"',
        )

    def test_manage_return_to_incoming_document_survives_save_and_delete(self):
        self.grant_permission(self.user, 'view_incomingtransaction')
        self.grant_permission(self.user, 'change_transaction')
        self.grant_permission(self.user, 'delete_transaction')
        document = self.create_incoming_document()
        incoming_document_url = reverse(
            'transactions:incoming_document',
            args=[document.pk],
        )
        incoming_query = f'?incoming_document={document.pk}'

        saved_transaction = self.create_transaction(self.user)
        saved_incoming_row = self.create_incoming_transaction(
            document,
            row_number=1,
        )
        saved_incoming_row.transaction = saved_transaction
        saved_incoming_row.save(update_fields=['transaction'])
        saved_manage_url = reverse(
            'transactions:transaction_manage',
            args=[saved_transaction.pk],
        )
        page = self.client.get(f'{saved_manage_url}{incoming_query}')
        self.assertEqual(
            page.context['transaction_list_url'],
            incoming_document_url,
        )

        save_response = self.client.post(
            f'{saved_manage_url}{incoming_query}',
            {'action': 'save', 'price': '20.75', 'quantity': '2'},
        )
        self.assertRedirects(
            save_response,
            incoming_document_url,
            fetch_redirect_response=False,
        )

        deleted_transaction = self.create_transaction(self.user)
        deleted_incoming_row = self.create_incoming_transaction(
            document,
            row_number=2,
        )
        deleted_incoming_row.transaction = deleted_transaction
        deleted_incoming_row.save(update_fields=['transaction'])
        delete_response = self.client.post(
            f'{reverse("transactions:transaction_manage", args=[deleted_transaction.pk])}'
            f'{incoming_query}',
            {'action': 'delete'},
        )
        self.assertRedirects(
            delete_response,
            incoming_document_url,
            fetch_redirect_response=False,
        )

    def test_toggle_verification_preserves_incoming_document_return_target(self):
        self.grant_permission(self.user, 'view_incomingtransaction')
        self.grant_permission(self.user, 'verify_transaction')
        document = self.create_incoming_document()
        transaction = self.create_transaction(self.user)
        transaction.is_verified = True
        transaction.verified_by = self.user
        transaction.save(update_fields=['is_verified', 'verified_by'])
        incoming_row = self.create_incoming_transaction(document)
        incoming_row.transaction = transaction
        incoming_row.save(update_fields=['transaction'])
        manage_url = reverse(
            'transactions:transaction_manage',
            args=[transaction.pk],
        )
        query = f'?incoming_document={document.pk}'

        response = self.client.post(
            f'{manage_url}{query}',
            {'action': 'toggle_verification'},
        )

        expected_manage_url = f'{manage_url}{query}'
        self.assertRedirects(
            response,
            expected_manage_url,
            fetch_redirect_response=False,
        )
        page = self.client.get(expected_manage_url)
        self.assertEqual(page.context['transaction_list_url'], reverse(
            'transactions:incoming_document',
            args=[document.pk],
        ))

    def test_edit_form_preserves_list_page_in_its_post_url(self):
        self.grant_permission(self.user, 'change_transaction')
        transaction = self.create_transaction(self.user)
        manage_url = reverse('transactions:transaction_manage', args=[transaction.id])

        response = self.client.get(f'{manage_url}?page=2')

        self.assertContains(response, f'action="{manage_url}?page=2"')

    def test_save_returns_to_the_transaction_list_page(self):
        self.grant_permission(self.user, 'change_transaction')
        transaction = self.create_transaction(self.user)

        response = self.client.post(
            f'{reverse("transactions:transaction_manage", args=[transaction.id])}?page=2',
            {'action': 'save', 'price': '20.75', 'quantity': '4'},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            f'{reverse("transactions:transaction_list")}?page=2',
        )

    def test_delete_returns_to_the_transaction_list_page(self):
        self.grant_permission(self.user, 'delete_transaction')
        transaction = self.create_transaction(self.user)

        response = self.client.post(
            f'{reverse("transactions:transaction_manage", args=[transaction.id])}?page=2',
            {'action': 'delete'},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            f'{reverse("transactions:transaction_list")}?page=2',
        )

    def test_manage_page_saves_transactions_without_item_price(self):
        self.grant_permission(self.user, 'change_transaction')
        self.item.price = None
        self.item.save(update_fields=['price'])
        transaction = self.create_transaction(self.user)

        response = self.client.post(
            reverse('transactions:transaction_manage', args=[transaction.id]),
            {'action': 'save', 'quantity': '4'},
        )

        self.assertRedirects(response, reverse('transactions:transaction_list'))
        transaction.refresh_from_db()
        self.assertEqual(transaction.price, Decimal('12.50'))
        self.assertEqual(transaction.quantity, 4)

    def test_manage_page_saves_zero_price_item_without_posted_quantity(self):
        self.grant_permission(self.user, 'change_transaction')
        self.item.price = Decimal('0.00')
        self.item.save(update_fields=['price'])
        transaction = self.create_transaction(self.user)

        response = self.client.post(
            reverse('transactions:transaction_manage', args=[transaction.id]),
            {'action': 'save', 'price': '20.75'},
        )

        self.assertRedirects(response, reverse('transactions:transaction_list'))
        transaction.refresh_from_db()
        self.assertEqual(transaction.price, Decimal('20.75'))
        self.assertEqual(transaction.quantity, 1)

    def test_manage_page_rejects_edit_without_change_permission(self):
        transaction = self.create_transaction(self.user)

        response = self.client.post(
            reverse('transactions:transaction_manage', args=[transaction.id]),
            {'action': 'save', 'price': '20.75', 'quantity': '4'},
        )

        self.assertEqual(response.status_code, 403)
        transaction.refresh_from_db()
        self.assertEqual(transaction.price, Decimal('12.50'))
        self.assertEqual(transaction.quantity, 1)

    def test_user_without_verify_permission_cannot_edit_verified_transaction(self):
        self.grant_permission(self.user, 'change_transaction')
        transaction = self.create_transaction(self.user)
        transaction.is_verified = True
        transaction.save(update_fields=['is_verified'])

        response = self.client.post(
            reverse('transactions:transaction_manage', args=[transaction.id]),
            {'action': 'save', 'price': '20.75', 'quantity': '4'},
        )

        self.assertEqual(response.status_code, 403)
        transaction.refresh_from_db()
        self.assertEqual(transaction.price, Decimal('12.50'))
        self.assertEqual(transaction.quantity, 1)

    def test_user_with_verify_permission_cannot_edit_verified_transaction(self):
        self.grant_permission(self.user, 'change_transaction')
        self.grant_permission(self.user, 'verify_transaction')
        transaction = self.create_transaction(self.user)
        transaction.is_verified = True
        transaction.save(update_fields=['is_verified'])

        response = self.client.post(
            reverse('transactions:transaction_manage', args=[transaction.id]),
            {'action': 'save', 'price': '20.75', 'quantity': '4'},
        )

        self.assertEqual(response.status_code, 403)
        transaction.refresh_from_db()
        self.assertEqual(transaction.price, Decimal('12.50'))
        self.assertEqual(transaction.quantity, 1)

    def test_manage_page_soft_deletes_transaction_with_delete_permission(self):
        self.grant_permission(self.user, 'delete_transaction')
        transaction = self.create_transaction(self.user)

        response = self.client.post(
            reverse('transactions:transaction_manage', args=[transaction.id]),
            {'action': 'delete'},
        )

        self.assertRedirects(response, reverse('transactions:transaction_list'))
        self.assertFalse(Transaction.objects.filter(pk=transaction.pk).exists())
        self.assertTrue(
            Transaction.objects.all_with_deleted().filter(
                pk=transaction.pk,
                is_deleted=True,
            ).exists()
        )

    def test_user_without_verify_permission_cannot_delete_verified_transaction(self):
        self.grant_permission(self.user, 'delete_transaction')
        transaction = self.create_transaction(self.user)
        transaction.is_verified = True
        transaction.save(update_fields=['is_verified'])

        response = self.client.post(
            reverse('transactions:transaction_manage', args=[transaction.id]),
            {'action': 'delete'},
        )

        self.assertEqual(response.status_code, 403)
        transaction.refresh_from_db()
        self.assertFalse(transaction.is_deleted)

    def test_user_with_verify_permission_can_delete_verified_transaction(self):
        self.grant_permission(self.user, 'delete_transaction')
        self.grant_permission(self.user, 'verify_transaction')
        transaction = self.create_transaction(self.user)
        transaction.is_verified = True
        transaction.save(update_fields=['is_verified'])

        response = self.client.post(
            reverse('transactions:transaction_manage', args=[transaction.id]),
            {'action': 'delete'},
        )

        self.assertRedirects(response, reverse('transactions:transaction_list'))
        transaction.refresh_from_db()
        self.assertTrue(transaction.is_deleted)

    def test_user_with_verify_permission_can_verify_transaction(self):
        self.grant_permission(self.user, 'change_transaction')
        self.grant_permission(self.user, 'verify_transaction')
        transaction = self.create_transaction(self.user)
        transaction.created_at = timezone.make_aware(datetime(2025, 1, 2, 12))
        transaction.save(update_fields=['created_at'])
        for minute in range(6):
            other_transaction = self.create_transaction(self.user)
            other_transaction.created_at = timezone.make_aware(
                datetime(2025, 1, 2, 13, minute)
            )
            other_transaction.save(update_fields=['created_at'])

        response = self.client.post(
            f"{reverse('transactions:transaction_manage', args=[transaction.id])}"
            "?unverified=1&date_from=2025-01-02&date_to=2025-01-03"
            "&preset=week&page=2",
            {
                'action': 'save_and_verify',
                'price': '20.75',
                'quantity': '4',
            },
        )

        self.assertRedirects(
            response,
            f"{reverse('transactions:transaction_list')}"
            "?unverified=1&date_from=2025-01-02&date_to=2025-01-03"
            "&preset=week&page=2",
        )
        transaction.refresh_from_db()
        self.assertTrue(transaction.is_verified)
        self.assertEqual(transaction.verified_by, self.user)
        self.assertEqual(transaction.price, Decimal('20.75'))
        self.assertEqual(transaction.quantity, 4)

    def test_verification_does_not_happen_when_transaction_changes_are_invalid(self):
        self.grant_permission(self.user, 'change_transaction')
        self.grant_permission(self.user, 'verify_transaction')
        transaction = self.create_transaction(self.user)

        response = self.client.post(
            reverse('transactions:transaction_manage', args=[transaction.id]),
            {
                'action': 'save_and_verify',
                'price': '-1.00',
                'quantity': '4',
            },
        )

        self.assertEqual(response.status_code, 400)
        transaction.refresh_from_db()
        self.assertFalse(transaction.is_verified)
        self.assertEqual(transaction.price, Decimal('12.50'))
        self.assertEqual(transaction.quantity, 1)

    def test_user_with_verify_permission_can_unverify_transaction(self):
        self.grant_permission(self.user, 'verify_transaction')
        transaction = self.create_transaction(self.user)
        transaction.is_verified = True
        transaction.verified_by = self.other_user
        transaction.created_at = timezone.make_aware(datetime(2025, 1, 2, 12))
        transaction.save(update_fields=['is_verified', 'verified_by'])

        response = self.client.post(
            f"{reverse('transactions:transaction_manage', args=[transaction.id])}"
            "?unverified=1&date_from=2025-01-02&date_to=2025-01-03"
            "&preset=week&page=1",
            {'action': 'toggle_verification'},
        )

        self.assertRedirects(
            response,
            f"{reverse('transactions:transaction_manage', args=[transaction.id])}"
            "?unverified=1&date_from=2025-01-02&date_to=2025-01-03"
            "&preset=week&page=1",
        )
        transaction.refresh_from_db()
        self.assertFalse(transaction.is_verified)
        self.assertIsNone(transaction.verified_by)

    def test_toggle_then_save_and_verify_keeps_plain_list_page(self):
        self.grant_permission(self.user, 'change_transaction')
        self.grant_permission(self.user, 'verify_transaction')
        transaction = self.create_transaction(self.user)
        transaction.is_verified = True
        transaction.verified_by = self.other_user
        transaction.save(update_fields=['is_verified', 'verified_by'])
        manage_url = reverse(
            'transactions:transaction_manage',
            args=[transaction.id],
        )

        toggle_response = self.client.post(
            f'{manage_url}?page=2',
            {'action': 'toggle_verification'},
        )

        expected_manage_url = f'{manage_url}?page=2'
        self.assertRedirects(
            toggle_response,
            expected_manage_url,
            fetch_redirect_response=False,
        )

        verify_response = self.client.post(
            expected_manage_url,
            {
                'action': 'save_and_verify',
                'price': '20.75',
                'quantity': '4',
            },
        )

        self.assertRedirects(
            verify_response,
            f'{reverse("transactions:transaction_list")}?page=2',
            fetch_redirect_response=False,
        )

    def test_user_without_verify_permission_cannot_toggle_verification(self):
        transaction = self.create_transaction(self.user)

        response = self.client.post(
            reverse('transactions:transaction_manage', args=[transaction.id]),
            {'action': 'toggle_verification'},
        )

        self.assertEqual(response.status_code, 403)
        transaction.refresh_from_db()
        self.assertFalse(transaction.is_verified)

    def test_manage_page_rejects_access_to_another_cashiers_transaction(self):
        transaction = self.create_transaction(self.other_user)

        response = self.client.get(
            reverse('transactions:transaction_manage', args=[transaction.id])
        )

        self.assertEqual(response.status_code, 403)

    def test_manage_page_hides_actions_user_does_not_have_permission_for(self):
        transaction = self.create_transaction(self.user)

        response = self.client.get(
            reverse('transactions:transaction_manage', args=[transaction.id])
        )

        self.assertNotContains(response, 'name="action" value="save"')
        self.assertNotContains(response, 'name="action" value="delete"')
        self.assertNotContains(response, 'name="action" value="toggle_verification"')

    def test_manage_page_hides_edit_and_delete_actions_for_verified_transaction(self):
        self.grant_permission(self.user, 'change_transaction')
        self.grant_permission(self.user, 'delete_transaction')
        transaction = self.create_transaction(self.user)
        transaction.is_verified = True
        transaction.save(update_fields=['is_verified'])

        response = self.client.get(
            reverse('transactions:transaction_manage', args=[transaction.id])
        )

        self.assertNotContains(response, 'name="action" value="save"')
        self.assertNotContains(response, 'name="action" value="delete"')

    def test_manage_page_shows_verified_transaction_as_read_only_to_verifier(self):
        self.grant_permission(self.user, 'change_transaction')
        self.grant_permission(self.user, 'verify_transaction')
        transaction = self.create_transaction(self.user)
        transaction.is_verified = True
        transaction.save(update_fields=['is_verified'])

        response = self.client.get(
            reverse('transactions:transaction_manage', args=[transaction.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="action" value="save"')
        self.assertNotContains(response, 'name="price"')
        self.assertContains(response, 'Сумма:')
        self.assertRegex(response.content.decode(), r'12[.,]50')

    def test_superuser_sees_all_transactions(self):
        superuser = get_user_model().objects.create_superuser(
            username='admin',
            password='test-password',
        )
        self.create_transaction(self.user)
        other_transaction = self.create_transaction(self.other_user)
        self.client.force_login(superuser)

        response = self.client.get(reverse('transactions:transaction_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, other_transaction.cashier.username)
        self.assertEqual(response.context['paginator'].count, 2)

    def test_transaction_list_uses_five_item_pagination(self):
        for _ in range(6):
            self.create_transaction(self.user)

        response = self.client.get(reverse('transactions:transaction_list'))

        self.assertEqual(response.context['page_obj'].paginator.per_page, 5)
        self.assertEqual(response.context['page_obj'].object_list.count(), 5)
        self.assertContains(response, 'page=2')

    def test_item_type_button_leads_to_creation_form_for_its_type(self):
        response = self.client.get(reverse('transactions:item_type_select'))

        self.assertContains(response, self.item_type.name)
        self.assertContains(
            response,
            f'href="{reverse("transactions:transaction_create", args=[self.item_type.id])}"',
        )

        response = self.client.get(
            reverse('transactions:transaction_create', args=[self.item_type.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'>{self.item.name}</p>')
        self.assertContains(response, f'type="hidden" name="item" value="{self.item.id}"')
        self.assertNotContains(response, '<select name="item"')
        self.assertNotContains(response, reverse('transactions:product_search'))

    def test_open_list_type_opens_name_and_price_form_even_without_active_items(self):
        self.item_type.is_open_list = True
        self.item_type.save(update_fields=['is_open_list'])
        self.item.is_active = False
        self.item.save(update_fields=['is_active'])

        response = self.client.get(reverse('transactions:item_type_select'))

        open_list_url = reverse(
            'transactions:new_open_list_item',
            args=[self.item_type.id],
        )
        self.assertContains(response, f'href="{open_list_url}"')
        self.assertNotContains(response, 'disabled')

        response = self.client.get(open_list_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="name"')
        self.assertContains(response, 'name="price"')
        self.assertNotContains(response, 'name="quantity"')
        self.assertNotContains(response, 'name="keep_active"')

    def test_open_list_form_creates_item_and_transaction(self):
        self.item_type.is_open_list = True
        self.item_type.save(update_fields=['is_open_list'])

        response = self.client.post(
            reverse('transactions:new_open_list_item', args=[self.item_type.id]),
            {'name': 'Разовая треба', 'price': '7.50'},
        )

        self.assertRedirects(response, reverse('transactions:item_type_select'))
        item = Item.objects.get(item_type=self.item_type, name='Разовая треба')
        self.assertEqual(item.price, Decimal('7.50'))
        transaction = Transaction.objects.get(item=item)
        self.assertEqual(transaction.cashier, self.user)
        self.assertEqual(transaction.price, Decimal('7.50'))
        self.assertEqual(transaction.quantity, 1)

    def test_open_list_form_reuses_existing_item_and_updates_its_price(self):
        self.item_type.is_open_list = True
        self.item_type.save(update_fields=['is_open_list'])
        item_count = Item.objects.filter(item_type=self.item_type).count()

        response = self.client.post(
            reverse('transactions:new_open_list_item', args=[self.item_type.id]),
            {'name': self.item.name.upper(), 'price': '15.00'},
        )

        self.assertRedirects(response, reverse('transactions:item_type_select'))
        self.assertEqual(Item.objects.filter(item_type=self.item_type).count(), item_count)
        self.item.refresh_from_db()
        self.assertEqual(self.item.price, Decimal('15.00'))
        transaction = Transaction.objects.get()
        self.assertEqual(transaction.item, self.item)
        self.assertEqual(transaction.price, Decimal('15.00'))

    def test_open_list_suggestions_are_30_latest_unique_names_for_same_type(self):
        self.item_type.is_open_list = True
        self.item_type.save(update_fields=['is_open_list'])
        base_time = timezone.now() - timedelta(days=1)
        items = [
            Item.objects.create(
                item_type=self.item_type,
                name=f'Позиция {index}',
                handle=f'open-list-item-{index}',
                price=Decimal('1.00'),
                order_number=index + 1,
            )
            for index in range(32)
        ]
        for index, item in enumerate(items):
            Transaction.objects.create(
                item=item,
                price=Decimal('1.00'),
                cashier=self.user,
                created_at=base_time + timedelta(minutes=index),
            )
        Transaction.objects.create(
            item=items[31],
            price=Decimal('1.00'),
            cashier=self.user,
            created_at=base_time + timedelta(minutes=33),
        )
        other_type = ItemType.objects.create(
            name='Другая открытая категория',
            handle='another-open-list',
            is_open_list=True,
            order_number=2,
        )
        other_item = Item.objects.create(
            item_type=other_type,
            name='Не показывать',
            handle='not-suggested',
            price=Decimal('1.00'),
        )
        Transaction.objects.create(
            item=other_item,
            price=Decimal('1.00'),
            cashier=self.user,
            created_at=base_time + timedelta(days=1),
        )

        response = self.client.get(
            reverse('transactions:new_open_list_item', args=[self.item_type.id])
        )

        suggestions = list(response.context['recent_item_names'])
        self.assertEqual(len(suggestions), 30)
        self.assertEqual(suggestions[0], 'Позиция 31')
        self.assertEqual(suggestions[-1], 'Позиция 2')
        self.assertNotIn('Не показывать', suggestions)
        self.assertEqual(suggestions.count('Позиция 31'), 1)
        self.assertContains(response, '<datalist id="recent-item-names">')

    def test_multiple_items_show_item_dropdown_and_item_type_name(self):
        additional_item = Item.objects.create(
            item_type=self.item_type,
            name='Дополнительная позиция',
            handle='additional-item',
            price=Decimal('8.00'),
            order_number=2,
        )

        response = self.client.get(
            reverse('transactions:transaction_create', args=[self.item_type.id])
        )

        self.assertContains(response, f'>{self.item_type.name}</p>')
        self.assertContains(response, '<select name="item"')
        self.assertContains(response, f'>{self.item.name}</option>')
        self.assertContains(response, f'>{additional_item.name}</option>')
        self.assertNotContains(response, 'type="hidden" name="item"')

    def test_bank_receipt_transaction_date_is_displayed_and_saved(self):
        bank_receipt = Item.objects.get(handle='bank-receipt')

        response = self.client.get(
            reverse(
                'transactions:transaction_create',
                args=[bank_receipt.item_type_id],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="created-at-field-container" hidden')
        self.assertContains(response, '["bank-receipt"]')
        self.assertContains(response, f'"{bank_receipt.pk}": "bank-receipt"')
        self.assertContains(response, 'type="datetime-local"')
        self.assertContains(response, 'lang="ru"')
        self.assertContains(response, 'name="created_at"')
        initial_created_at = timezone.make_aware(
            response.context['form']['created_at'].value()
        )
        self.assertContains(
            response,
            f'value="{initial_created_at.strftime("%Y-%m-%dT%H:%M")}"',
        )
        current_time = timezone.localtime()
        self.assertLess(
            abs((initial_created_at - current_time).total_seconds()),
            60,
        )

        response = self.client.post(
            reverse(
                'transactions:transaction_create',
                args=[bank_receipt.item_type_id],
            ),
            {
                'item': bank_receipt.pk,
                'price': '5.00',
                'quantity': '1',
                'created_at': '2026-10-31T14:37',
            },
        )

        self.assertRedirects(response, reverse('transactions:item_type_select'))
        transaction = Transaction.objects.get(item=bank_receipt)
        self.assertEqual(timezone.localtime(transaction.created_at).year, 2026)
        self.assertEqual(timezone.localtime(transaction.created_at).month, 10)
        self.assertEqual(timezone.localtime(transaction.created_at).day, 31)
        self.assertEqual(timezone.localtime(transaction.created_at).hour, 14)
        self.assertEqual(timezone.localtime(transaction.created_at).minute, 37)

    def test_transaction_date_is_not_saved_for_other_item_handles(self):
        response = self.client.post(
            reverse('transactions:transaction_create', args=[self.item_type.id]),
            {
                'item': self.item.pk,
                'price': '',
                'quantity': '1',
                'created_at': '2026-10-31T14:37',
            },
        )

        self.assertRedirects(response, reverse('transactions:item_type_select'))
        transaction = Transaction.objects.get(item=self.item)
        self.assertNotEqual(
            timezone.localtime(transaction.created_at).date(),
            datetime(2026, 10, 31).date(),
        )

    def test_products_button_opens_product_group_types(self):
        product_group = ItemType.objects.create(
            name='Тестовая группа товаров',
            handle='test-product-group',
            order_number=2,
            is_product_group=True,
        )
        Item.objects.create(
            item_type=product_group,
            name='Позиция группы',
            handle='product-group-item',
            price=Decimal('5.00'),
            order_number=1,
        )
        response = self.client.get(reverse('transactions:item_type_select'))

        self.assertContains(
            response,
            f'href="{reverse("transactions:product_group_select")}"',
        )
        self.assertContains(
            response,
            f'href="{reverse("transactions:product_search")}"',
        )
        self.assertContains(response, 'Товары')
        self.assertNotContains(response, product_group.name)

        response = self.client.get(reverse('transactions:product_group_select'))

        self.assertContains(response, product_group.name)
        self.assertContains(
            response,
            f'href="{reverse("transactions:transaction_create", args=[product_group.id])}"',
        )
        self.assertNotContains(response, f'href="{reverse("transactions:product_group_select")}"')
        self.assertNotContains(response, self.item_type.name)

    def test_product_search_lists_only_active_product_group_items_and_selects_item(self):
        product_group = ItemType.objects.create(
            name='Товары для поиска',
            handle='searchable-products',
            is_product_group=True,
        )
        item = Item.objects.create(
            item_type=product_group,
            name='Икона для поиска',
            handle='searchable-icon',
            price=Decimal('80.00'),
        )
        Item.objects.create(
            item_type=product_group,
            name='Другая икона',
            handle='other-searchable-icon',
            price=Decimal('45.00'),
        )
        inactive_item = Item.objects.create(
            item_type=product_group,
            name='Неактивный товар',
            handle='inactive-search-product',
            is_active=False,
        )

        response = self.client.get(reverse('transactions:product_search'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, item.name)
        self.assertNotContains(response, inactive_item.name)
        self.assertNotContains(response, self.item.name)

        response = self.client.get(
            reverse('transactions:product_search'),
            {'item': item.pk},
        )

        self.assertContains(response, product_group.name)
        self.assertContains(response, item.name)
        self.assertContains(response, '80.00 руб.')
        self.assertContains(
            response,
            f'href="{reverse("transactions:transaction_create", args=[product_group.pk])}?item={item.pk}"',
        )

        response = self.client.get(
            reverse('transactions:transaction_create', args=[product_group.pk]),
            {'item': item.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'value="{item.pk}" selected')
        self.assertContains(
            response,
            f'href="{reverse("transactions:product_search")}?item={item.pk}"',
        )

    def test_product_search_cannot_select_inactive_or_non_product_items(self):
        product_group = ItemType.objects.create(
            name='Группа для проверки',
            handle='product-group-check',
            is_product_group=True,
        )
        inactive_item = Item.objects.create(
            item_type=product_group,
            name='Неактивный товар для проверки',
            handle='inactive-product-check',
            is_active=False,
        )

        response = self.client.get(
            reverse('transactions:product_search'),
            {'item': inactive_item.pk},
        )

        self.assertRedirects(response, reverse('welcome_landing'))

        response = self.client.get(
            reverse('transactions:product_search'),
            {'item': self.item.pk},
        )

        self.assertRedirects(response, reverse('welcome_landing'))

        active_product = Item.objects.create(
            item_type=product_group,
            name='Активный товар из другой категории',
            handle='active-product-other-category',
        )
        response = self.client.get(
            reverse('transactions:transaction_create', args=[self.item_type.pk]),
            {'item': active_product.pk},
        )

        self.assertRedirects(response, reverse('welcome_landing'))

    def test_product_group_page_has_new_product_button_after_item_types(self):
        response = self.client.get(reverse('transactions:product_group_select'))

        self.assertNotContains(response, 'Новый товар')

        self.grant_directory_permission(self.user, 'add_item')
        response = self.client.get(reverse('transactions:product_group_select'))

        self.assertContains(
            response,
            f'href="{reverse("transactions:new_product_transaction")}"',
        )
        self.assertContains(response, 'Новый товар')

    def test_new_product_requires_directory_add_item_permission(self):
        create_url = reverse('transactions:new_product_transaction')

        response = self.client.get(create_url)
        self.assertEqual(response.status_code, 403)

        response = self.client.post(
            create_url,
            {
                'name': 'Недоступный товар',
                'price': '25.50',
                'quantity': '1',
                'keep_active': 'on',
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Item.objects.filter(name='Недоступный товар').exists())
        self.assertFalse(Transaction.objects.exists())

    def test_new_product_creates_item_in_others_and_transaction(self):
        self.grant_directory_permission(self.user, 'add_item')
        create_url = reverse('transactions:new_product_transaction')

        response = self.client.post(
            create_url,
            {
                'name': 'Новая книга',
                'price': '25.50',
                'quantity': '2',
                'keep_active': 'on',
            },
        )

        self.assertRedirects(response, reverse('transactions:product_group_select'))
        item_type = ItemType.objects.get(name='Others')
        self.assertTrue(item_type.is_product_group)
        item = Item.objects.get(name='Новая книга')
        self.assertEqual(item.item_type, item_type)
        self.assertTrue(item.is_active)
        transaction = Transaction.objects.get(item=item)
        self.assertEqual(transaction.cashier, self.user)
        self.assertEqual(transaction.price, Decimal('25.50'))
        self.assertEqual(transaction.quantity, 2)

    def test_new_product_can_be_created_inactive(self):
        self.grant_directory_permission(self.user, 'add_item')
        self.client.post(
            reverse('transactions:new_product_transaction'),
            {
                'name': 'Разовый товар',
                'price': '8.00',
                'quantity': '1',
            },
        )

        item = Item.objects.get(name='Разовый товар')
        self.assertFalse(item.is_active)
        self.assertTrue(Transaction.objects.filter(item=item).exists())

    def test_existing_item_name_is_reused_without_creating_duplicate(self):
        self.grant_directory_permission(self.user, 'add_item')
        existing_item = Item.objects.create(
            item_type=self.item_type,
            name='Уже в справочнике',
            handle='already-in-directory',
            price=Decimal('3.00'),
            order_number=2,
        )
        item_count = Item.objects.count()

        response = self.client.post(
            reverse('transactions:new_product_transaction'),
            {
                'name': 'уже в справочнике',
                'price': '4.50',
                'quantity': '3',
                'keep_active': 'on',
            },
        )

        self.assertRedirects(response, reverse('transactions:product_group_select'))
        self.assertEqual(Item.objects.count(), item_count)
        transaction = Transaction.objects.get()
        self.assertEqual(transaction.item, existing_item)
        self.assertEqual(transaction.price, Decimal('4.50'))
        self.assertEqual(transaction.quantity, 3)
        self.assertFalse(ItemType.objects.filter(name='Others').exists())

    def test_item_type_without_active_items_has_disabled_button(self):
        inactive_type = ItemType.objects.create(
            name='Пустая категория',
            handle='empty-category',
            order_number=2,
        )
        response = self.client.get(reverse('transactions:item_type_select'))

        self.assertContains(
            response,
            f'<button class="btn btn-outline-secondary w-100 h-100 py-3 d-flex align-items-center justify-content-center fs-5" disabled>\n                            {inactive_type.name}\n                        </button>',
            html=True,
        )
        self.assertNotContains(
            response,
            f'href="{reverse("transactions:transaction_create", args=[inactive_type.id])}"',
        )

    def test_item_type_with_only_inactive_items_has_disabled_button(self):
        inactive_type = ItemType.objects.create(
            name='Категория без активных позиций',
            handle='inactive-category',
            order_number=2,
        )
        Item.objects.create(
            item_type=inactive_type,
            name='Неактивная позиция',
            handle='inactive-item',
            price=Decimal('1.00'),
            order_number=1,
            is_active=False,
        )

        response = self.client.get(reverse('transactions:item_type_select'))

        self.assertNotContains(
            response,
            f'href="{reverse("transactions:transaction_create", args=[inactive_type.id])}"',
        )

    def test_create_transaction_assigns_current_cashier(self):
        response = self.client.post(
            reverse('transactions:transaction_create', args=[self.item_type.id]),
            {
                'item': self.item.id,
                'price': '12.50',
                'quantity': 3,
            },
        )

        self.assertRedirects(response, reverse('transactions:transaction_list'))
        transaction = Transaction.objects.get()
        self.assertEqual(transaction.cashier, self.user)
        self.assertEqual(transaction.item, self.item)
        self.assertEqual(transaction.total_cost, Decimal('37.50'))

    def test_inactive_items_cannot_be_selected_for_new_transactions(self):
        self.item.is_active = False
        self.item.save(update_fields=['is_active'])

        response = self.client.post(
            reverse('transactions:transaction_create', args=[self.item_type.id]),
            {
                'item': self.item.id,
                'price': '12.50',
                'quantity': 1,
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Transaction.objects.exists())

    def test_item_without_price_hides_field_and_saves_zero(self):
        self.item.price = None
        self.item.save(update_fields=['price'])

        response = self.client.get(
            reverse('transactions:transaction_create', args=[self.item_type.id])
        )
        self.assertContains(response, '"%s": null' % self.item.id)
        self.assertContains(response, 'id="price-field-container"')

        response = self.client.post(
            reverse('transactions:transaction_create', args=[self.item_type.id]),
            {'item': self.item.id, 'quantity': 1},
        )

        self.assertRedirects(response, reverse('transactions:transaction_list'))
        transaction = Transaction.objects.get()
        self.assertEqual(transaction.price, Decimal('0.00'))

    def test_quantity_is_hidden_until_item_is_selected(self):
        response = self.client.get(
            reverse('transactions:transaction_create', args=[self.item_type.id])
        )

        self.assertContains(response, 'id="quantity-field-container" hidden')
        self.assertContains(
            response,
            'quantityContainer.hidden = !hasSelectedItem || (hasItemPrice && Number(itemPrice) === 0);',
        )

    def test_create_button_is_shown_only_when_an_item_is_selected(self):
        Item.objects.create(
            item_type=self.item_type,
            name='Дополнительная позиция',
            handle='additional-item-for-selection',
            price=Decimal('15.00'),
            order_number=2,
        )
        create_url = reverse(
            'transactions:transaction_create',
            args=[self.item_type.id],
        )

        response = self.client.get(create_url)
        self.assertContains(
            response,
            'id="create-transaction-button" class="btn btn-primary w-100 py-2 text-uppercase" hidden',
        )

        response = self.client.get(create_url, {'item': self.item.id})
        self.assertContains(
            response,
            'createTransactionButton.hidden = !hasSelectedItem;',
        )
        self.assertContains(response, f'value="{self.item.id}" selected')

    def test_zero_price_item_hides_quantity_field(self):
        self.item.price = Decimal('0.00')
        self.item.save(update_fields=['price'])

        response = self.client.get(
            reverse('transactions:transaction_create', args=[self.item_type.id])
        )

        self.assertContains(
            response,
            'quantityContainer.hidden = !hasSelectedItem || (hasItemPrice && Number(itemPrice) === 0);',
        )

    def test_item_without_price_shows_quantity(self):
        self.item.price = None
        self.item.save(update_fields=['price'])

        response = self.client.get(
            reverse('transactions:transaction_create', args=[self.item_type.id])
        )

        self.assertContains(
            response,
            'quantityContainer.hidden = !hasSelectedItem || (hasItemPrice && Number(itemPrice) === 0);',
        )

    def test_fixed_item_price_is_used_even_if_posted_price_is_tampered(self):
        response = self.client.post(
            reverse('transactions:transaction_create', args=[self.item_type.id]),
            {
                'item': self.item.id,
                'price': '0.01',
                'quantity': 1,
            },
        )

        self.assertRedirects(response, reverse('transactions:transaction_list'))
        self.assertEqual(Transaction.objects.get().price, Decimal('12.50'))

    def test_fixed_item_price_is_displayed_as_text(self):
        response = self.client.get(
            reverse('transactions:transaction_create', args=[self.item_type.id])
        )

        self.assertContains(response, 'id="price-display"')
        self.assertContains(response, 'priceInput.hidden = true;')
        self.assertContains(response, 'priceDisplay.textContent = itemPrice;')

    def test_zero_price_item_requires_a_custom_price_greater_than_zero(self):
        self.item.price = Decimal('0.00')
        self.item.save(update_fields=['price'])
        create_url = reverse(
            'transactions:transaction_create',
            args=[self.item_type.id],
        )

        for submitted_price in ('', '0', '0.00'):
            with self.subTest(price=submitted_price):
                response = self.client.post(
                    create_url,
                    {
                        'item': self.item.id,
                        'price': submitted_price,
                        'quantity': 1,
                    },
                )
                self.assertEqual(response.status_code, 400)
                self.assertFalse(Transaction.objects.exists())

        response = self.client.post(
            create_url,
            {
                'item': self.item.id,
                'price': '0.01',
                'quantity': 1,
            },
        )

        self.assertRedirects(response, reverse('transactions:transaction_list'))
        self.assertEqual(Transaction.objects.get().price, Decimal('0.01'))

    def test_incoming_documents_list_only_shows_documents_with_pending_active_rows(self):
        pending_document = self.create_incoming_document()
        pending_row = self.create_incoming_transaction(pending_document)
        processed_document = IncomingDocument.objects.create(
            document_type=DocumentType.CANDLE_REPORT,
            dropbox_file_id='processed-test-file',
            original_name='Обработано.xlsx',
            dropbox_path='/reports/Обработано.xlsx',
            local_file='dropbox/Обработано.xlsx',
        )
        processed_row = self.create_incoming_transaction(processed_document)
        processed_row.transaction = self.create_transaction(self.user)
        processed_row.save(update_fields=['transaction'])
        deleted_document = IncomingDocument.objects.create(
            document_type=DocumentType.PRODUCT_REPORT,
            dropbox_file_id='deleted-test-file',
            original_name='Удалено.xlsx',
            dropbox_path='/reports/Удалено.xlsx',
            local_file='dropbox/Удалено.xlsx',
        )
        self.create_incoming_transaction(deleted_document).delete_soft()

        response = self.client.get(reverse('transactions:incoming_documents'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, pending_document.original_name)
        self.assertNotContains(response, processed_document.original_name)
        self.assertNotContains(response, deleted_document.original_name)
        self.assertEqual(response.context['documents'][0].incoming_pending_count, 1)
        self.assertEqual(
            response.context['documents'][0].incoming_manual_review_count,
            0,
        )
        self.assertIsNone(pending_row.transaction_id)

    def test_incoming_documents_list_uses_archive_style_and_conflict_badge(self):
        document = self.create_incoming_document()
        self.create_incoming_transaction(
            document,
            raw_counts=[1],
            quantity=2,
        )

        response = self.client.get(reverse('transactions:incoming_documents'))

        self.assertContains(
            response,
            f'href="{reverse("transactions:incoming_document", args=[document.pk])}" class="report-title-link"',
        )
        self.assertContains(
            response,
            '<span class="badge bg-warning-subtle text-warning-emphasis">',
        )
        self.assertContains(response, 'bi-box-seam text-success')
        self.assertContains(response, '.text-secondary-soft')
        self.assertNotContains(response, 'class="card')
        self.assertNotContains(response, 'Открыть')

    def test_incoming_document_bulk_add_creates_only_matched_rows_and_links_them(self):
        self.grant_permission(self.user, 'view_incomingtransaction')
        self.grant_permission(self.user, 'verify_transaction')
        document = self.create_incoming_document()
        matched = self.create_incoming_transaction(
            document,
            raw_counts=[1, 2],
            quantity=3,
            row_number=1,
            report_date=date(2025, 3, 4),
        )
        needs_review = self.create_incoming_transaction(
            document,
            item=None,
            use_default_item=False,
            raw_counts=[1],
            row_number=2,
        )
        self.assertTrue(matched.is_matched)
        self.assertFalse(needs_review.is_matched)
        url = reverse('transactions:incoming_document', args=[document.pk])

        response = self.client.post(url, {'action': 'add_matched'})

        self.assertRedirects(response, url)
        matched.refresh_from_db()
        needs_review.refresh_from_db()
        created = matched.transaction
        self.assertIsNotNone(created)
        self.assertEqual(created.item, self.item)
        self.assertEqual(created.price, Decimal('12.50'))
        self.assertEqual(created.quantity, 3)
        self.assertEqual(created.cashier, self.user)
        self.assertTrue(created.is_verified)
        self.assertEqual(created.verified_by, self.user)
        self.assertEqual(matched.processed_by, self.user)
        self.assertIsNone(needs_review.transaction_id)
        self.assertEqual(Transaction.objects.count(), 1)

    def test_incoming_document_bulk_add_redirects_when_no_pending_rows_remain(self):
        self.grant_permission(self.user, 'view_incomingtransaction')
        self.grant_permission(self.user, 'verify_transaction')
        document = self.create_incoming_document()
        incoming = self.create_incoming_transaction(document)

        response = self.client.post(
            reverse('transactions:incoming_document', args=[document.pk]),
            {'action': 'add_matched'},
        )

        self.assertRedirects(response, reverse('transactions:incoming_documents'))
        incoming.refresh_from_db()
        self.assertIsNotNone(incoming.transaction_id)

    def test_incoming_document_lists_pending_and_processed_rows(self):
        self.grant_permission(self.user, 'view_incomingtransaction')
        document = self.create_incoming_document()
        pending = self.create_incoming_transaction(
            document,
            row_number=1,
        )
        processed = self.create_incoming_transaction(
            document,
            row_number=2,
        )
        transaction = self.create_transaction(self.user)
        processed.transaction = transaction
        processed.save(update_fields=['transaction'])
        url = reverse('transactions:incoming_document', args=[document.pk])

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'href="{reverse("transactions:incoming_transaction_detail", args=[pending.pk])}"',
        )
        self.assertContains(
            response,
            f'href="{reverse("transactions:transaction_manage", args=[transaction.pk])}'
            f'?incoming_document={document.pk}"',
        )
        self.assertRegex(
            response.content.decode(),
            r'<i class="bi bi-check-circle-fill text-primary[^"]*" title="Транзакция создана"',
        )
        self.assertRegex(
            response.content.decode(),
            r'text-body-(?:secondary|tertiary)',
        )
        self.assertEqual(len(response.context['incoming_rows']), 2)
        self.assertEqual(response.context['pending_rows_count'], 1)
        self.assertEqual(response.context['matched_rows_count'], 1)

    def test_incoming_document_marks_soft_deleted_related_transaction(self):
        self.grant_permission(self.user, 'view_incomingtransaction')
        document = self.create_incoming_document()
        incoming = self.create_incoming_transaction(document)
        transaction = self.create_transaction(self.user)
        incoming.transaction = transaction
        incoming.save(update_fields=['transaction'])
        transaction.delete_soft()

        response = self.client.get(
            reverse('transactions:incoming_document', args=[document.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            '<i class="bi bi-check-circle-fill text-danger fs-6 ms-1" '
            'title="Связанная транзакция удалена"',
        )
        self.assertTrue(response.context['incoming_rows'][0].is_transaction_deleted)

    def test_deleted_transaction_requires_incoming_document_context_to_view(self):
        transaction = self.create_transaction(self.user)
        transaction.delete_soft()

        response = self.client.get(
            reverse('transactions:transaction_manage', args=[transaction.pk])
        )

        self.assertEqual(response.status_code, 404, response.get('Location'))

    def test_deleted_transaction_context_requires_incoming_review_permission(self):
        document = self.create_incoming_document()
        transaction = self.create_transaction(self.user)
        transaction.delete_soft()

        response = self.client.get(
            f'{reverse("transactions:transaction_manage", args=[transaction.pk])}'
            f'?incoming_document={document.pk}'
        )

        self.assertEqual(response.status_code, 404)

    def test_deleted_transaction_is_read_only_when_opened_from_incoming_document(self):
        self.grant_permission(self.user, 'view_incomingtransaction')
        self.grant_permission(self.user, 'change_transaction')
        self.grant_permission(self.user, 'delete_transaction')
        self.grant_permission(self.user, 'verify_transaction')
        document = self.create_incoming_document()
        incoming = self.create_incoming_transaction(document)
        transaction = self.create_transaction(self.user)
        incoming.transaction = transaction
        incoming.save(update_fields=['transaction'])
        transaction.delete_soft()
        incoming_document_url = reverse(
            'transactions:incoming_document',
            args=[document.pk],
        )
        manage_url = (
            f'{reverse("transactions:transaction_manage", args=[transaction.pk])}'
            f'?incoming_document={document.pk}'
        )

        response = self.client.get(manage_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Удалена')
        self.assertContains(response, f'href="{incoming_document_url}"')
        self.assertNotContains(response, 'name="action" value="save"')
        self.assertNotContains(response, 'name="action" value="save_and_verify"')
        self.assertNotContains(response, 'name="action" value="toggle_verification"')
        self.assertNotContains(response, 'name="action" value="delete"')
        self.assertEqual(response.context['transaction_list_url'], incoming_document_url)

        post_response = self.client.post(
            manage_url,
            {'action': 'delete'},
        )
        self.assertEqual(post_response.status_code, 403)

    def test_incoming_document_delete_all_soft_deletes_only_unprocessed_rows(self):
        self.grant_permission(self.user, 'view_incomingtransaction')
        document = self.create_incoming_document()
        pending = self.create_incoming_transaction(document, row_number=1)
        processed = self.create_incoming_transaction(document, row_number=2)
        processed.transaction = self.create_transaction(self.user)
        processed.save(update_fields=['transaction'])
        url = reverse('transactions:incoming_document', args=[document.pk])

        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'name="action" value="delete_all"')
        self.assertNotContains(page, '<table')

        response = self.client.post(url, {'action': 'delete_all'})

        self.assertRedirects(response, reverse('transactions:incoming_documents'))
        self.assertFalse(IncomingTransaction.objects.filter(pk=pending.pk).exists())
        self.assertTrue(
            IncomingTransaction.objects.all_with_deleted().filter(
                pk=pending.pk,
                is_deleted=True,
            ).exists()
        )
        self.assertTrue(IncomingTransaction.objects.filter(pk=processed.pk).exists())
        processed.refresh_from_db()
        self.assertIsNotNone(processed.transaction_id)
        self.assertTrue(
            any(
                'Содержимое документа удалено' in str(message)
                for message in response.wsgi_request._messages
            )
        )

    def test_individual_incoming_creation_uses_transaction_form_values_and_report_date(self):
        document = self.create_incoming_document()
        incoming = self.create_incoming_transaction(
            document,
            price=Decimal('9.75'),
            quantity=2,
            report_date=date(2025, 3, 4),
        )
        create_url = reverse(
            'transactions:transaction_create',
            args=[self.item_type.pk],
        )
        query = {'incoming_transaction': incoming.pk}

        form_response = self.client.get(create_url, query)

        self.assertEqual(form_response.status_code, 200)
        self.assertContains(form_response, document.original_name)
        self.assertContains(form_response, 'value="9.75"')
        self.assertContains(form_response, 'value="2"')
        self.assertContains(form_response, 'value="2025-03-04T12:00"')
        self.assertContains(form_response, 'name="incoming_transaction"')

        response = self.client.post(
            f'{create_url}?incoming_transaction={incoming.pk}',
            {
                'item': self.item.pk,
                'price': '9.75',
                'quantity': '2',
                'created_at': '2025-03-04T12:00',
            },
        )

        self.assertRedirects(
            response,
            reverse('transactions:incoming_document', args=[document.pk]),
        )
        incoming.refresh_from_db()
        self.assertIsNotNone(incoming.transaction_id)
        self.assertEqual(incoming.processed_by, self.user)
        self.assertEqual(incoming.transaction.price, Decimal('9.75'))
        self.assertEqual(incoming.transaction.quantity, 2)
        self.assertEqual(
            timezone.localtime(incoming.transaction.created_at).date(),
            date(2025, 3, 4),
        )
        self.assertFalse(incoming.transaction.is_verified)

    def test_incoming_routes_require_login_and_review_permission(self):
        document = self.create_incoming_document()
        incoming = self.create_incoming_transaction(document)
        self.client.logout()

        response = self.client.get(reverse('transactions:incoming_documents'))

        self.assertEqual(response.status_code, 302)

        self.client.force_login(self.other_user)
        response = self.client.get(reverse('transactions:incoming_documents'))
        self.assertEqual(response.status_code, 403)

        self.grant_permission(self.other_user, 'verify_transaction')
        response = self.client.get(reverse('transactions:incoming_documents'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.client.get(reverse('transactions:home')).status_code,
            200,
        )

        create_url = reverse(
            'transactions:transaction_create',
            args=[self.item_type.pk],
        )
        response = self.client.post(
            f'{create_url}?incoming_transaction={incoming.pk}',
            {
                'item': self.item.pk,
                'price': '12.50',
                'quantity': '1',
            },
        )

        self.assertRedirects(
            response,
            reverse('transactions:incoming_document', args=[document.pk]),
        )
        incoming.refresh_from_db()
        self.assertTrue(incoming.transaction.is_verified)
        self.assertEqual(incoming.transaction.verified_by, self.other_user)

    def test_incoming_row_can_be_corrected_and_soft_deleted(self):
        document = self.create_incoming_document()
        incoming = self.create_incoming_transaction(
            document,
            raw_counts=[1, 1],
            quantity=1,
        )
        detail_url = reverse(
            'transactions:incoming_transaction_detail',
            args=[incoming.pk],
        )

        response = self.client.post(
            detail_url,
            {
                'action': 'save',
                'item': self.item.pk,
                'report_date': '2025-03-04',
                'price': '12.50',
                'quantity': '2',
            },
        )

        self.assertRedirects(response, detail_url)
        incoming.refresh_from_db()
        self.assertEqual(incoming.report_date, date(2025, 3, 4))
        self.assertEqual(incoming.quantity, 2)
        self.assertTrue(incoming.is_matched)

        response = self.client.post(detail_url, {'action': 'delete'})

        self.assertRedirects(
            response,
            reverse('transactions:incoming_document', args=[document.pk]),
        )
        self.assertFalse(IncomingTransaction.objects.filter(pk=incoming.pk).exists())
        self.assertTrue(
            IncomingTransaction.objects.all_with_deleted().filter(
                pk=incoming.pk,
                is_deleted=True,
            ).exists()
        )

    def test_home_incoming_documents_button_is_active_only_when_pending_rows_exist(self):
        response = self.client.get(reverse('transactions:home'))
        self.assertContains(response, 'Входящие документы')
        self.assertContains(response, 'disabled')

        document = self.create_incoming_document()
        self.create_incoming_transaction(document)
        response = self.client.get(reverse('transactions:home'))

        self.assertContains(
            response,
            f'href="{reverse("transactions:incoming_documents")}"',
        )
        self.assertContains(response, 'Документов: 1 / строк: 1')

    def test_incoming_detail_displays_actual_raw_counts_sum_and_handles_invalid_values(self):
        document = self.create_incoming_document()
        mismatched = self.create_incoming_transaction(
            document,
            raw_counts=[1, 1, 4],
            quantity=50,
        )
        mismatch_url = reverse(
            'transactions:incoming_transaction_detail',
            args=[mismatched.pk],
        )

        response = self.client.get(mismatch_url)

        self.assertContains(response, '[1, 1, 4] (сумма: 6)')
        self.assertContains(
            response,
            'Сумма распознанных количеств (6) не совпадает с количеством (50)',
        )
        document_response = self.client.get(
            reverse('transactions:incoming_document', args=[document.pk])
        )
        self.assertContains(
            document_response,
            '<tr class="bg-warning-subtle border-warning border-start border-3">',
        )
        self.assertContains(
            document_response,
            '<td class="text-end text-nowrap bg-warning-subtle">',
        )
        self.assertContains(
            document_response,
            '<td class="text-nowrap bg-warning-subtle">',
        )
        self.assertContains(document_response, 'class="small text-warning-emphasis"')
        self.assertContains(
            document_response,
            'Сумма распознанных количеств (6) не совпадает с количеством (50).',
        )

        matched = self.create_incoming_transaction(
            document,
            raw_counts=[1, 1, 4],
            quantity=6,
            row_number=2,
        )
        response = self.client.get(
            reverse(
                'transactions:incoming_transaction_detail',
                args=[matched.pk],
            )
        )
        self.assertContains(response, 'Сумма распознанных количеств (6) совпадает с количеством (6)')

        empty_counts = self.create_incoming_transaction(
            document,
            raw_counts=[],
            quantity=1,
            row_number=3,
        )
        response = self.client.get(
            reverse(
                'transactions:incoming_transaction_detail',
                args=[empty_counts.pk],
            )
        )
        self.assertContains(response, '[] (сумма: 0)')

        invalid_counts = self.create_incoming_transaction(
            document,
            raw_counts=['not-a-number'],
            quantity=1,
            row_number=4,
        )
        response = self.client.get(
            reverse(
                'transactions:incoming_transaction_detail',
                args=[invalid_counts.pk],
            )
        )
        self.assertContains(response, 'сумма: не вычислена')
        self.assertContains(
            response,
            'Сумма распознанных количеств (не вычислена) не совпадает с количеством (1)',
        )

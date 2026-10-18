from decimal import Decimal

from directory.models import Item, ItemType
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from .models import Transaction


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

    def create_transaction(self, cashier, item=None):
        return Transaction.objects.create(
            cashier=cashier,
            item=item or self.item,
            price=Decimal('12.50'),
            quantity=1,
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
        self.assertContains(response, self.item_type.name)
        self.assertContains(response, f'>{self.item.name}</option>')
        self.assertNotContains(response, f'>[{self.item_type.name}] {self.item.name}')

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

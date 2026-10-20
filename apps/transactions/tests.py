from datetime import timedelta
from decimal import Decimal

from directory.models import Item, ItemType
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

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

    def test_user_with_view_all_permission_sees_other_cashiers_transactions(self):
        self.grant_permission(self.user, 'view_all_transactions')
        other_transaction = self.create_transaction(self.other_user)

        response = self.client.get(reverse('transactions:transaction_list'))

        self.assertContains(response, str(other_transaction.item.name))
        self.assertContains(response, str(self.other_user.username))

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

    def test_product_group_page_has_new_product_button_after_item_types(self):
        response = self.client.get(reverse('transactions:product_group_select'))

        self.assertContains(
            response,
            f'href="{reverse("transactions:new_product_transaction")}"',
        )
        self.assertContains(response, 'Новый товар')

    def test_new_product_creates_item_in_others_and_transaction(self):
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

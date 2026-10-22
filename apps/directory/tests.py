from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from .models import Item, ItemType


class DirectoryViewsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='directory-user',
            password='test-password',
        )
        permissions = Permission.objects.filter(
            content_type__app_label='directory',
            codename__in=('view_item', 'view_itemtype'),
        )
        self.user.user_permissions.add(*permissions)
        self.client.force_login(self.user)

    def create_item_type(self, name, handle, **kwargs):
        return ItemType.objects.create(
            name=name,
            handle=handle,
            order_number=ItemType.objects.count() + 1,
            **kwargs,
        )

    def create_item(self, item_type, name, handle, price, is_active=True):
        return Item.objects.create(
            item_type=item_type,
            name=name,
            handle=handle,
            price=price,
            is_active=is_active,
        )

    def grant_permission(self, codename):
        permission = Permission.objects.get(
            content_type__app_label='directory',
            codename=codename,
        )
        self.user.user_permissions.add(permission)

    def remove_permission(self, codename):
        permission = Permission.objects.get(
            content_type__app_label='directory',
            codename=codename,
        )
        self.user.user_permissions.remove(permission)

    def test_home_lists_product_groups_and_types_with_nonzero_price_items(self):
        product_group = self.create_item_type(
            'Каталог тестовая группа товаров',
            'catalog-test-product-group',
            is_product_group=True,
        )
        priced_type = self.create_item_type('Каталог тест платные позиции', 'catalog-test-priced')
        zero_price_type = self.create_item_type('Каталог тест бесплатные позиции', 'catalog-test-free')
        no_price_type = self.create_item_type('Каталог тест без цены', 'catalog-test-no-price')
        self.create_item(
            priced_type,
            'Каталог тест платная позиция',
            'catalog-test-priced-item',
            Decimal('5.00'),
            is_active=False,
        )
        self.create_item(
            zero_price_type,
            'Каталог тест бесплатная позиция',
            'catalog-test-free-item',
            Decimal('0.00'),
        )
        self.create_item(
            no_price_type,
            'Каталог тест позиция без цены',
            'catalog-test-no-price-item',
            None,
        )

        response = self.client.get(reverse('directory:home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, product_group.name)
        self.assertContains(response, priced_type.name)
        self.assertNotContains(response, zero_price_type.name)
        self.assertNotContains(response, no_price_type.name)
        self.assertContains(
            response,
            f'href="{reverse("directory:item_type_detail", args=[priced_type.pk])}"',
        )

    def test_item_type_detail_shows_name_type_price_and_active_status(self):
        item_type = self.create_item_type('Каталог тест пожертвования', 'catalog-test-donations')
        item = self.create_item(
            item_type,
            'Каталог тест на ремонт',
            'catalog-test-repair-donation',
            Decimal('25.50'),
            is_active=False,
        )

        response = self.client.get(
            reverse('directory:item_type_detail', args=[item_type.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, item.name)
        self.assertContains(response, item_type.name)
        self.assertContains(response, '25')
        self.assertContains(response, 'Снято с продажи')

    def test_item_type_detail_shows_only_items_with_nonzero_prices(self):
        item_type = self.create_item_type(
            'Каталог цены',
            'catalog-price-filter',
        )
        priced_item = self.create_item(
            item_type,
            'Каталог позиция с ценой',
            'catalog-priced-item',
            Decimal('25.50'),
        )
        self.create_item(
            item_type,
            'Каталог позиция нулевая',
            'catalog-zero-price-item',
            Decimal('0.00'),
        )
        self.create_item(
            item_type,
            'Каталог позиция без цены',
            'catalog-no-price-item',
            None,
        )

        response = self.client.get(
            reverse('directory:item_type_detail', args=[item_type.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, priced_item.name)
        self.assertNotContains(response, 'Каталог позиция нулевая')
        self.assertNotContains(response, 'Каталог позиция без цены')

    def test_item_type_detail_uses_five_item_pagination(self):
        item_type = self.create_item_type('Каталог тест пагинация', 'catalog-test-pagination')
        items = [
            self.create_item(
                item_type,
                f'Каталог позиция {index}',
                f'catalog-pagination-{index}',
                Decimal('1.00'),
            )
            for index in range(7)
        ]
        detail_url = reverse('directory:item_type_detail', args=[item_type.pk])

        first_page = self.client.get(detail_url)
        self.assertEqual(first_page.status_code, 200)
        self.assertEqual(first_page.context['paginator'].per_page, 5)
        self.assertEqual(first_page.context['page_obj'].object_list.count(), 5)
        self.assertContains(first_page, items[0].name)
        self.assertContains(first_page, 'page=2')
        self.assertNotContains(first_page, items[6].name)

        second_page = self.client.get(detail_url, {'page': 2})
        self.assertEqual(second_page.context['page_obj'].object_list.count(), 2)
        self.assertContains(second_page, items[6].name)
        self.assertNotContains(second_page, items[0].name)

    def test_item_rows_link_to_item_detail(self):
        item_type = self.create_item_type('Каталог тест ссылки', 'catalog-test-links')
        item = self.create_item(
            item_type,
            'Каталог ссылка позиция',
            'catalog-link-item',
            Decimal('4.00'),
        )

        response = self.client.get(
            reverse('directory:item_type_detail', args=[item_type.pk])
        )

        self.assertContains(
            response,
            f'href="{reverse("directory:item_detail", args=[item.pk])}?page=1"',
        )

    def test_item_detail_edits_type_name_price_and_order_number(self):
        self.grant_permission('change_item')
        self.grant_permission('change_itemtype')
        item_type = self.create_item_type('Каталог исходный тип', 'catalog-source-type')
        new_type = self.create_item_type('Каталог новый тип', 'catalog-new-type')
        item = self.create_item(
            item_type,
            'Каталог старая позиция',
            'catalog-edit-item',
            Decimal('3.00'),
        )

        detail_url = reverse('directory:item_detail', args=[item.pk])
        response = self.client.post(
            f'{detail_url}?page=2',
            {
                'action': 'save',
                'item_type': new_type.pk,
                'name': 'Каталог новая позиция',
                'price': '19.25',
                'order_number': '7',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            f'{reverse("directory:item_type_detail", args=[item_type.pk])}?page=2',
        )
        item.refresh_from_db()
        self.assertEqual(item.item_type, new_type)
        self.assertEqual(item.name, 'Каталог новая позиция')
        self.assertEqual(item.price, Decimal('19.25'))
        self.assertEqual(item.order_number, 7)

    def test_item_type_is_read_only_without_change_itemtype_permission(self):
        self.grant_permission('change_item')
        item_type = self.create_item_type(
            'Каталог неизменяемая категория',
            'catalog-fixed-category',
        )
        other_type = self.create_item_type(
            'Каталог поддельная категория',
            'catalog-forged-category',
        )
        item = self.create_item(
            item_type,
            'Каталог редактирование без категории',
            'catalog-edit-no-category',
            Decimal('3.00'),
        )
        detail_url = reverse('directory:item_detail', args=[item.pk])

        get_response = self.client.get(detail_url)
        self.assertContains(get_response, 'Каталог')
        self.assertContains(get_response, item_type.name)
        self.assertNotContains(get_response, 'name="item_type"')

        post_response = self.client.post(
            detail_url,
            {
                'action': 'save',
                'item_type': other_type.pk,
                'name': 'Обновленное название',
                'price': '19.25',
                'order_number': '7',
            },
        )

        self.assertEqual(post_response.status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.item_type, item_type)
        self.assertEqual(item.name, 'Обновленное название')
        self.assertEqual(item.price, Decimal('19.25'))
        self.assertEqual(item.order_number, 7)

    def test_item_detail_return_link_keeps_items_list_page(self):
        item_type = self.create_item_type(
            'Каталог возврат страницы',
            'catalog-return-page',
        )
        item = self.create_item(
            item_type,
            'Каталог возврат позиция',
            'catalog-return-item',
            Decimal('3.00'),
        )

        response = self.client.get(
            f'{reverse("directory:item_detail", args=[item.pk])}?page=2'
        )

        self.assertContains(
            response,
            f'href="{reverse("directory:item_type_detail", args=[item_type.pk])}?page=2"',
        )

    def test_toggle_active_keeps_item_list_page_for_return(self):
        self.grant_permission('delete_item')
        item_type = self.create_item_type(
            'Каталог переключение страницы',
            'catalog-toggle-page',
        )
        item = self.create_item(
            item_type,
            'Каталог позиция переключение',
            'catalog-toggle-page-item',
            Decimal('3.00'),
        )
        detail_url = reverse('directory:item_detail', args=[item.pk])
        detail_url_with_page = f'{detail_url}?page=2'

        detail_response = self.client.get(detail_url_with_page)
        self.assertContains(
            detail_response,
            f'action="{detail_url_with_page}"',
        )

        toggle_response = self.client.post(
            detail_url_with_page,
            {'action': 'toggle_active'},
            follow=False,
        )

        self.assertEqual(toggle_response.status_code, 302)
        self.assertEqual(toggle_response.url, detail_url_with_page)
        detail_response = self.client.get(toggle_response.url)
        self.assertContains(
            detail_response,
            f'href="{reverse("directory:item_type_detail", args=[item_type.pk])}?page=2"',
        )

    def test_item_detail_rejects_edits_without_change_permission(self):
        item_type = self.create_item_type('Каталог без прав', 'catalog-no-change')
        item = self.create_item(
            item_type,
            'Каталог неизменная позиция',
            'catalog-unchanged-item',
            Decimal('3.00'),
        )

        response = self.client.post(
            reverse('directory:item_detail', args=[item.pk]),
            {
                'action': 'save',
                'item_type': item_type.pk,
                'name': 'Измененное',
                'price': '19.25',
                'order_number': '7',
            },
        )

        self.assertEqual(response.status_code, 403)
        item.refresh_from_db()
        self.assertEqual(item.name, 'Каталог неизменная позиция')
        self.assertEqual(item.price, Decimal('3.00'))

    def test_item_detail_can_activate_and_deactivate_with_change_permission(self):
        self.grant_permission('delete_item')
        item_type = self.create_item_type('Каталог статус', 'catalog-status')
        item = self.create_item(
            item_type,
            'Каталог позиция статуса',
            'catalog-status-item',
            Decimal('3.00'),
            is_active=False,
        )
        detail_url = reverse('directory:item_detail', args=[item.pk])

        response = self.client.post(detail_url, {'action': 'toggle_active'})

        self.assertRedirects(response, detail_url)
        item.refresh_from_db()
        self.assertTrue(item.is_active)
        detail_response = self.client.get(detail_url)
        self.assertContains(detail_response, 'name="action" value="toggle_active"')
        self.assertNotContains(detail_response, 'name="action" value="save"')

        response = self.client.post(detail_url, {'action': 'toggle_active'})

        self.assertRedirects(response, detail_url)
        item.refresh_from_db()
        self.assertFalse(item.is_active)

    def test_item_detail_rejects_status_change_without_delete_permission(self):
        self.grant_permission('change_item')
        item_type = self.create_item_type('Каталог статус без прав', 'catalog-status-no-change')
        item = self.create_item(
            item_type,
            'Каталог защищенная позиция',
            'catalog-protected-item',
            Decimal('3.00'),
        )

        response = self.client.post(
            reverse('directory:item_detail', args=[item.pk]),
            {'action': 'toggle_active'},
        )

        self.assertEqual(response.status_code, 403)
        item.refresh_from_db()
        self.assertTrue(item.is_active)

    def test_item_detail_can_change_status_with_delete_permission_only(self):
        self.grant_permission('delete_item')
        item_type = self.create_item_type(
            'Каталог только удаление',
            'catalog-delete-only',
        )
        item = self.create_item(
            item_type,
            'Каталог позиция удаление',
            'catalog-delete-only-item',
            Decimal('3.00'),
            is_active=False,
        )
        detail_url = reverse('directory:item_detail', args=[item.pk])

        response = self.client.post(detail_url, {'action': 'toggle_active'})

        self.assertRedirects(response, detail_url)
        item.refresh_from_db()
        self.assertTrue(item.is_active)

    def test_directory_views_require_view_item_permission(self):
        self.remove_permission('view_itemtype')
        self.remove_permission('view_item')

        home_response = self.client.get(reverse('directory:home'))
        detail_response = self.client.get(
            reverse('directory:item_type_detail', args=[1])
        )

        self.assertEqual(home_response.status_code, 403)
        self.assertEqual(detail_response.status_code, 403)

    def test_view_itemtype_permission_allows_type_pages_without_item_details(self):
        self.remove_permission('view_item')
        item_type = self.create_item_type(
            'Каталог только тип просмотр',
            'catalog-type-view-only',
            is_product_group=True,
        )
        item = self.create_item(
            item_type,
            'Каталог закрытая карточка',
            'catalog-type-view-item',
            Decimal('2.00'),
        )

        list_response = self.client.get(reverse('directory:home'))
        type_response = self.client.get(
            reverse('directory:item_type_detail', args=[item_type.pk])
        )
        item_response = self.client.get(
            reverse('directory:item_detail', args=[item.pk])
        )

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(type_response.status_code, 200)
        self.assertNotContains(
            type_response,
            f'href="{reverse("directory:item_detail", args=[item.pk])}?page=1"',
        )
        self.assertEqual(item_response.status_code, 403)

    def test_item_view_permission_allows_item_details_without_type_pages(self):
        self.remove_permission('view_itemtype')
        item_type = self.create_item_type(
            'Каталог item view тип',
            'catalog-item-view-type',
        )
        item = self.create_item(
            item_type,
            'Каталог item view позиция',
            'catalog-item-view-item',
            Decimal('2.00'),
        )

        item_response = self.client.get(
            reverse('directory:item_detail', args=[item.pk])
        )

        self.assertEqual(item_response.status_code, 200)
        self.assertNotContains(
            item_response,
            f'href="{reverse("directory:item_type_detail", args=[item_type.pk])}"',
        )
        self.assertEqual(
            self.client.get(reverse('directory:home')).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(
                reverse('directory:item_type_detail', args=[item_type.pk])
            ).status_code,
            403,
        )

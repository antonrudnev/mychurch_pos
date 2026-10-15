from django.contrib import admin
from django.utils.html import format_html

from .models import Item, ItemType


@admin.register(ItemType)
class ItemTypeAdmin(admin.ModelAdmin):
    """Настройка отображения типов номенклатуры в админке"""
    list_display = ('id', 'name')
    prepopulated_fields = {'handle': ('name',)}
    list_display_links = ('id', 'name')


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    """Настройка отображения реестра товаров и услуг в админке"""
    list_display = ('get_id_with_meta', 'name', 'item_type', 'price', 'is_active', 'created_at')
    prepopulated_fields = {'handle': ('name',)}

    # Теперь клик по названию или ID открывает карточку редактирования
    list_display_links = ('get_id_with_meta', 'name')
    
    # Поля, которые можно редактировать прямо в списке
    list_editable = ('price', 'is_active')
    
    # Фильтры в правой панели
    list_filter = ('item_type', 'is_active', 'created_at')
    
    # Строка поиска теперь ищет только по названию товара/услуги
    search_fields = ('name__icontains',)
    
    # Группировка полей внутри карточки товара/услуги
    fieldsets = (
        ('Основная информация', {
            'fields': ('item_type', 'name', 'handle', 'price')
        }),
        ('Статус', {
            'fields': ('is_active',)
        }),
    )

    @admin.display(description='ID', ordering='id')
    def get_id_with_meta(self, obj):
        """Передаем на страницу списка флаг: заполнена ли цена у товара"""
        has_price = "true" if obj.price is not None else "false"
        return format_html('<span class="item-meta" data-has-price="{}">{}</span>', has_price, obj.id)

    class Media:
        # Подключаем новый JS-скрипт, который скроет инпуты цен там, где они не нужны
        js = ('admin/js/hide_free_prices.js',)
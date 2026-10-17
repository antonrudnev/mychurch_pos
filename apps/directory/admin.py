from django.contrib import admin

from .models import Item, ItemType


@admin.register(ItemType)
class ItemTypeAdmin(admin.ModelAdmin):
    """Настройка отображения типов номенклатуры в админке"""
    list_display = ('id', 'name', 'is_product_group', 'order_number')
    prepopulated_fields = {'handle': ('name',)}
    list_display_links = ('name',)
    list_editable = ('order_number',)


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    """Настройка отображения реестра товаров и услуг в админке"""
    list_display = ('id', 'display_handle', 'name', 'item_type', 'display_price', 'is_active', 'order_number')
    prepopulated_fields = {'handle': ('name',)}

    # Теперь клик по названию или ID открывает карточку редактирования
    list_display_links = ('name',)
    
    # Поля, которые можно редактировать прямо в списке
    list_editable = ('order_number',)
    
    # Фильтры в правой панели
    list_filter = ('item_type', 'item_type__is_product_group', 'is_active')
    
    # Строка поиска теперь ищет только по названию товара/услуги
    search_fields = ('name__icontains', 'handle__icontains', 'item_type__name__icontains')
    
    # Группировка полей внутри карточки товара/услуги
    fieldsets = (
        ('Основная информация', {
            'fields': ('item_type', 'name', 'handle', 'price')
        }),
        ('Статус', {
            'fields': ('is_active', 'order_number')
        }),
    )

    @admin.display(description='Артикул', ordering='handle')
    def display_handle(self, obj):
        if obj.item_type.is_product_group:
            return obj.handle
        return ''

    @admin.display(description='Цена / Рекомендуемый взнос', ordering='price')
    def display_price(self, obj):
        if obj.price is None:
            return ""
        return obj.price if obj.price > 0 else "Сумма по запросу"
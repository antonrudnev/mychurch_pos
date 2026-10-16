from django.contrib import admin

from .models import Item, ItemType


@admin.register(ItemType)
class ItemTypeAdmin(admin.ModelAdmin):
    """Настройка отображения типов номенклатуры в админке"""
    list_display = ('id', 'name', 'is_product_group', 'order')
    prepopulated_fields = {'handle': ('name',)}
    list_display_links = ('name',)
    list_editable = ('order',)


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    """Настройка отображения реестра товаров и услуг в админке"""
    list_display = ('id', 'handle', 'name', 'item_type', 'price', 'is_active', 'order')
    prepopulated_fields = {'handle': ('name',)}

    # Теперь клик по названию или ID открывает карточку редактирования
    list_display_links = ('name',)
    
    # Поля, которые можно редактировать прямо в списке
    list_editable = ('order',)
    
    # Фильтры в правой панели
    list_filter = ('item_type', 'is_active')
    
    # Строка поиска теперь ищет только по названию товара/услуги
    search_fields = ('name__icontains', 'handle__icontains', 'item_type__name__icontains')
    
    # Группировка полей внутри карточки товара/услуги
    fieldsets = (
        ('Основная информация', {
            'fields': ('item_type', 'name', 'handle', 'price')
        }),
        ('Статус', {
            'fields': ('is_active', 'order')
        }),
    )

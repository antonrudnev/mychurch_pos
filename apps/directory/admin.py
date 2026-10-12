from django.contrib import admin

from .models import Item, ItemType


@admin.register(ItemType)
class ItemTypeAdmin(admin.ModelAdmin):
    """Настройка отображения типов номенклатуры в админке"""
    list_display = ('name', 'slug', 'has_stock')
    prepopulated_fields = {'slug': ('name',)}  # Автоматически генерирует slug из названия
    search_fields = ('name',)


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    """Настройка отображения реестра товаров и услуг в админке"""
    # Столбцы, которые будут видны в общем списке
    list_display = ('id', 'name', 'item_type', 'price', 'stock', 'is_active', 'created_at')
    
    # Теперь клик по названию или ID открывает карточку редактирования
    list_display_links = ('id', 'name')
    
    # Поля, которые можно редактировать прямо в списке
    list_editable = ('price', 'stock', 'is_active')
    
    # Фильтры в правой панели
    list_filter = ('item_type', 'is_active', 'created_at')
    
    # Строка поиска теперь ищет только по названию товара/услуги
    search_fields = ('name',)
    
    # Группировка полей внутри карточки товара/услуги
    fieldsets = (
        ('Основная информация', {
            'fields': ('item_type', 'name',)
        }),
        ('Финансы и Склад', {
            'fields': ('price', 'stock')
        }),
        ('Статус', {
            'fields': ('is_active',)
        }),
    )
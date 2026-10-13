import json
from datetime import timedelta

from directory.models import Item
from django.contrib import admin
from django.utils import timezone
from django.utils.safestring import mark_safe

from .models import Transaction


class TransactionDateFilter(admin.SimpleListFilter):
    title = 'Дата и время'
    parameter_name = 'date_range'

    

    def lookups(self, request, model_admin):
        # Если в URL уже есть параметры точного дня/месяца/года от date_hierarchy,
        # мы скрываем быстрые периоды, так как пользователь уже выбрал конкретную дату
        if any(key.startswith('created_at__') for key in request.GET.keys()):
            return (
                ('custom', 'Выбран календарь 📅'),
            )
        return (
            ('today', 'Сегодня'),
            ('yesterday', 'Вчера'),
            ('this_week', 'Эта неделя'),
            ('this_month', 'Этот месяц'),
        )

    def queryset(self, request, queryset):
        # 1. Если пользователь выбрал дату через date_hierarchy, в URL появятся параметры 'created_at__...'
        # В этом случае кастомный фильтр не должен перебивать выбор календаря — отдаем queryset как есть
        if any(key.startswith('created_at__') for key in request.GET.keys()):
            return queryset
        # 2. Иначе обрабатываем стандартные клики по нашей правой панели
        # Получаем текущее локальное время
        now = timezone.localtime(timezone.now())
        # Начало сегодняшнего дня (00:00:00)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        if self.value() == 'today':
            return queryset.filter(created_at__gte=today_start)
            
        if self.value() == 'yesterday':
            yesterday_start = today_start - timedelta(days=1)
            yesterday_end = today_start
            return queryset.filter(created_at__gte=yesterday_start, created_at__lt=yesterday_end)
            
        if self.value() == 'this_week':
            # Вычисляем номер текущей недели в году и текущий год
            current_week = now.isocalendar()[1]
            return queryset.filter(created_at__year=now.year, created_at__week=current_week)
            
        if self.value() == 'this_month':
            return queryset.filter(created_at__year=now.year, created_at__month=now.month)
            
        return queryset
    
class DeletedFilter(admin.SimpleListFilter):
    """Кастомный фильтр для отображения удаленных записей"""
    title = 'Статус удаления'
    parameter_name = 'deleted_status'

    def lookups(self, request, model_admin):
        return (
            ('active', 'Активные (по умолчанию)'),
            ('deleted', 'Только удаленные (Корзина)'),
            ('all', 'Все записи (включая удаленные)'),
        )

    def queryset(self, request, queryset):
        # По умолчанию (если фильтр не выбран) показываем только активные
        if self.value() == 'active' or self.value() is None:
            return queryset.filter(is_deleted=False)
        if self.value() == 'deleted':
            return queryset.filter(is_deleted=True)
        if self.value() == 'all':
            return queryset  # Возвращаем весь список без фильтрации по is_deleted


@admin.action(description='Утвердить выбранные транзакции (верификация)')
def make_verified(modeladmin, request, queryset):
    """Кастомное действие для аудитора: массовое утверждение транзакций"""
    queryset.update(is_verified=True, verified_by=request.user)

@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    """Настройка отображения Журнала транзакций в админке"""

    list_display = (
        'id', 'created_at', 'get_item_clean_name', 'price', 'quantity',
        'get_total_cost', 'is_cashless', 'is_verified', 'cashier', 'get_status'
    )
    list_display_links = ('id', 'created_at')
    list_filter = (DeletedFilter,'is_cashless', 'is_verified', TransactionDateFilter, 'cashier')
    search_fields = ('item__name__icontains', 'cashier__username__icontains')
    date_hierarchy = 'created_at'
    readonly_fields = ('get_total_cost', 'verified_by', 'cashier', 'is_deleted')
    actions = (make_verified,)

    @admin.display(description='Итоговая стоимость (руб.)')
    def get_total_cost(self, obj):
        """Вывод динамического свойства total_cost в таблицу админки"""
        return obj.total_cost

    @admin.display(ordering='item__name', description='Товар / Услуга')
    def get_item_clean_name(self, obj):
        """Выводит тип и название позиции без цены и лишней информации"""
        if obj.item:
            return f"[{obj.item.item_type.name}] {obj.item.name}"
        return "—"

    @admin.display(description='Статус')
    def get_status(self, obj):
        if obj.is_deleted:
            # Вариант с mark_safe для статической HTML-строки:
            return mark_safe('<span style="color: #ba2121; font-weight: bold;">Удалена</span>')
        return "Активна"

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        initial['cashier'] = request.user.id
        return initial
    
    def save_model(self, request, obj, form, change):
        """Автоматически подставляем текущего пользователя в качестве кассира или аудитора"""
        if not change:
            obj.cashier = request.user
        if obj.is_verified and not obj.verified_by:
            obj.verified_by = request.user
        elif not obj.is_verified:
            obj.verified_by = None
        super().save_model(request, obj, form, change)

    def get_queryset(self, request):
        """Позволяем администраторам видеть удаленные записи в корзине."""
        return Transaction.objects.all_with_deleted()

    def render_change_form(self, request, context, add=False, change=False, form_url='', obj=None):
        """Передаем словарь 'ID товара: Цена' в контекст страницы добавления транзакции"""
        items = Item.objects.filter(is_active=True)
        # Формируем JSON-словарь, например: {1: 150.00, 2: 50.00}
        item_prices = {item.id: float(item.price if item.price is not None else 0) for item in items}
        
        context['item_prices_json'] = json.dumps(item_prices)
        return super().render_change_form(request, context, add, change, form_url, obj)

    class Media:
        # Подключаем кастомный JS-файл, который будет отвечать за подстановку на стороне клиента
        js = ('admin/js/autofill_price.js',)

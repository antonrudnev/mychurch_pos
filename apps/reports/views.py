from directory.models import Item
from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.db.models import F, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.generic import ListView, TemplateView, View
from transactions.models import Transaction

from .models import Report, ReportType


class CashReportView(PermissionRequiredMixin, TemplateView):
    template_name = 'reports/cash_report.html'
    permission_required = 'reports.add_report'
    raise_exception = False

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(**kwargs)
        
        prefix = "treby"
        treby_data = (
            Item.objects
            .filter(item_type__handle__istartswith=prefix)
            .values(
                'name', 
                'order'
            )
            .annotate(total_quantity=Sum('transactions__quantity'))
            .order_by('order')
        )

        prefix = "product"
        product_data = (
            Transaction.objects
            .filter(item__item_type__handle__istartswith=prefix)
            .aggregate(total_cost=Sum(F('quantity') * F('price')))
            .get('total_cost')
        )
        
        prefix = "candle"
        candle_data = (
            Transaction.objects
            .filter(item__item_type__handle__istartswith=prefix)
            .aggregate(total_cost=Sum(F('quantity') * F('price')))
            .get('total_cost')
        )

        context['treby_data'] = treby_data
        context['product_data'] = product_data
        context['candle_data'] = candle_data
        context['current_time'] = timezone.now()
        context['current_user'] = self.request.user
        # По умолчанию мы НЕ сохраняем, кнопки должна быть видна на живой странице
        context['is_saving'] = False 
        return context

    def post(self, request, *args, **kwargs):
        # 1. Получаем базовый контекст
        context = self.get_context_data()
        
        # 2. Переключаем флаг: для сохранения в файл кнопка НЕ НУЖНА
        context['is_saving'] = True
        
        # Рендерим чистую HTML-страницу БЕЗ кнопки управления
        html_dump = render_to_string(self.template_name, context, request=request)
        
        # Формируем динамическое название с датой
        formatted_date = context['current_time'].strftime('%d.%m.%Y %H:%M')
        report_name = f"Кассовый отчет от {formatted_date}"

        # НАХОДИМ ИЛИ СОЗДАЕМ ТИП ОТЧЕТА ПО ХЕНДЛЕРУ
        # Если записи нет, она создастся с человеческим именем "Кассовый отчет"
        report_type_obj, _created = ReportType.objects.get_or_create(
            handle='cash-report',
            defaults={'name': 'Кассовый отчет'}
        )
        
        # 3. Записываем в базу чистый HTML
        Report.objects.create(
            name=report_name,
            report_type=report_type_obj, 
            created_by=request.user if request.user.is_authenticated else None,
            dump=html_dump
        )
        
        messages.success(request, f"'{report_name}' успешно сохранен")

        return redirect('reports:report_list')


class PrintReportView(PermissionRequiredMixin, View):
    permission_required = 'reports.view_report'
    raise_exception = True 

    def get(self, request, report_id, *args, **kwargs):
        report = get_object_or_404(Report, id=report_id)
        return HttpResponse(report.dump, content_type='text/html; charset=utf-8')


REPORT_CLASSES_REGISTRY = {
    'cash-report': CashReportView,
}


class DynamicReportRouterView(PermissionRequiredMixin, View):
    """Принимает строковый ключ из БД и вызывает привязанный класс Python"""
    permission_required = 'reports.add_report'
    raise_exception = False

    def dispatch(self, request, *args, **kwargs):
        handle_key = kwargs.get('handle_key')
        print(f"DynamicReportRouterView: handle_key = {handle_key}")  # Для отладки
        # Ищем класс в нашем реестре кодов
        target_view_class = REPORT_CLASSES_REGISTRY.get(handle_key)
        
        if target_view_class:
            # Динамически вызываем метод .as_view() у найденного класса и передаем ему управление
            return target_view_class.as_view()(request, *args, **kwargs)
        
        # Если класс в коде еще не написан, возвращаем пользователя в архив
        messages.error(request, "Этот тип документа еще не поддерживается системой.")
        return redirect('reports:report_list')


class ReportTypeSelectView(PermissionRequiredMixin, ListView):
    model = ReportType
    template_name = 'reports/report_type_select.html'
    context_object_name = 'report_types'
    permission_required = 'reports.add_report'
    raise_exception = False

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Получаем список всех handle-ключей, под которые написан код
        active_handles = list(REPORT_CLASSES_REGISTRY.keys())
        
        context['active_handles'] = active_handles
        return context


class ReportListView(PermissionRequiredMixin, ListView):
    model = Report
    template_name = 'reports/report_list.html'
    context_object_name = 'reports'
    permission_required = 'reports.view_report'
    raise_exception = False

    paginate_by = 5

    def get_queryset(self):
        return Report.objects.select_related('report_type', 'created_by').order_by('-created_at')
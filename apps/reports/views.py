from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.generic import ListView, TemplateView, View
from transactions.models import Transaction

from .models import Report, ReportType


class ReportListView(PermissionRequiredMixin, ListView):
    model = Report
    template_name = 'reports/report_list.html'
    context_object_name = 'reports'
    permission_required = 'reports.view_report'
    raise_exception = False

    def get_queryset(self):
        return Report.objects.select_related('report_type', 'created_by').order_by('-created_at')


class CashReportView(PermissionRequiredMixin, TemplateView):
    template_name = 'reports/cash_report.html'
    permission_required = 'reports.add_report'
    raise_exception = True

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        report_data = (
            Transaction.objects.values(
                'item__name', 
                'item__order'
            )
            .annotate(total_quantity=Sum('quantity'))
            .order_by('item__order')
        )
        
        context['report_data'] = report_data
        context['current_time'] = timezone.now()
        context['current_user'] = self.request.user
        # По умолчанию мы НЕ сохраняем, кнопка должна быть видна на живой странице
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
        
        messages.success(request, f"Отчет '{report_name}' успешно сохранен в архив!")
        return redirect(request.path)


class PrintReportView(PermissionRequiredMixin, View):
    permission_required = 'reports.view_report'
    raise_exception = True 

    def get(self, request, report_id, *args, **kwargs):
        report = get_object_or_404(Report, id=report_id)
        return HttpResponse(report.dump, content_type='text/html; charset=utf-8')

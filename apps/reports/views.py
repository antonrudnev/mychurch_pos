from directory.models import Item
from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.db.models import F, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.generic import ListView, TemplateView, View
from transactions.models import Transaction

from .forms import ReportDateRangeForm
from .models import Report, ReportType


class CashReportView(PermissionRequiredMixin, TemplateView):
    template_name = 'reports/report_date_range.html'
    permission_required = 'reports.add_report'
    raise_exception = False

    def get(self, request, *args, **kwargs):
        has_date_range = 'date_from' in request.GET or 'date_to' in request.GET
        form = ReportDateRangeForm(request.GET if has_date_range else None)
        if not has_date_range:
            return self.render_to_response({
                'form': form,
                'application_today': timezone.localdate(),
            })
        if not form.is_valid():
            return self.render_to_response({
                'form': form,
                'application_today': timezone.localdate(),
            }, status=400)
        self.template_name = 'reports/cash_report.html'
        return self.render_to_response(self.get_report_context(form))

    def post(self, request, *args, **kwargs):
        form = ReportDateRangeForm(request.POST)
        if not form.is_valid():
            return self.render_to_response({'form': form}, status=400)

        self.template_name = 'reports/cash_report.html'
        context = self.get_report_context(form)
        context['is_saving'] = True
        html_dump = render_to_string(self.template_name, context, request=request)

        date_from = form.cleaned_data['date_from']
        date_to = form.cleaned_data['date_to']
        report_name = (
            f"Кассовый отчет за {date_from:%d.%m.%Y} — {date_to:%d.%m.%Y}"
        )
        report_type_obj, _created = ReportType.objects.get_or_create(
            handle='cash-report',
            defaults={'name': 'Кассовый отчет'}
        )
        Report.objects.create(
            name=report_name,
            report_type=report_type_obj,
            created_by=request.user if request.user.is_authenticated else None,
            dump=html_dump
        )
        messages.success(request, f"'{report_name}' успешно сохранен")
        return redirect('reports:report_list')

    def get_report_context(self, form):
        date_from = form.cleaned_data['date_from']
        date_to = form.cleaned_data['date_to']
        date_range = (date_from, date_to)

        prefix = "treby"
        treby_data = (
            Item.objects
            .filter(item_type__handle__istartswith=prefix)
            .values(
                'name', 
                'handle',
            )
            .annotate(
                total_quantity=Sum(
                    'transactions__quantity',
                    filter=Q(
                        transactions__is_deleted=False,
                        transactions__created_at__date__range=date_range,
                    ),
                )
            )
            .order_by('handle')
        )

        prefix = "product"
        product_data = (
            Transaction.objects
            .filter(
                item__item_type__handle__istartswith=prefix,
                created_at__date__range=date_range,
            )
            .aggregate(total_cost=Sum(F('quantity') * F('price')))
            .get('total_cost')
        )

        prefix = "candle"
        candle_data = (
            Transaction.objects
            .filter(
                item__item_type__handle__istartswith=prefix,
                created_at__date__range=date_range,
            )
            .aggregate(total_cost=Sum(F('quantity') * F('price')))
            .get('total_cost')
        )

        prefix = "debt-lend"
        debt_lend_data = (
            Transaction.objects
            .filter(
                item__handle__iexact=prefix,
                created_at__date__range=date_range,
            )
            .aggregate(total_cost=Sum('price'))
            .get('total_cost')
        )

        prefix = "debt-repay"
        debt_repay_data = (
            Transaction.objects
            .filter(
                item__handle__iexact=prefix,
                created_at__date__range=date_range,
            )
            .aggregate(total_cost=Sum('price'))
            .get('total_cost')
        )

        prefix = "bank-terminal"
        bank_terminal_data = (
        Transaction.objects
        .filter(
            item__handle__iexact=prefix,
            created_at__date__range=date_range,
                )
                .aggregate(total_cost=Sum('price'))
                .get('total_cost')
            )

        prefix = "bank-receipt"
        bank_receipt_data = (
            Transaction.objects
            .filter(
                item__handle__iexact=prefix,
                created_at__date__range=date_range,
            )
            .aggregate(total_cost=Sum('price'))
            .get('total_cost')
        )

        prefix = "cash-register"
        cash_register_data = (
            Transaction.objects
            .filter(
                item__handle__iexact=prefix,
                created_at__date__range=date_range,
            )
            .order_by('-created_at')
            .first()
        )

        prefix = "cash-deposit"
        cash_deposit_data = (
            Transaction.objects
            .filter(
                item__handle__iexact=prefix,
                created_at__date__range=date_range,
            )
            .order_by('-created_at')
            .first()
        )

        context = {
            'treby_data': treby_data,
            'product_data': product_data,
            'candle_data': candle_data,
            'debt_lend_data': debt_lend_data,
            'debt_repay_data': debt_repay_data,
            'bank_terminal_data': bank_terminal_data,
            'bank_receipt_data': bank_receipt_data,
            'cash_register_data': cash_register_data,
            'cash_deposit_data': cash_deposit_data,
            'current_time': timezone.now(),
            'current_user': self.request.user,
            'date_from': date_from,
            'date_to': date_to,
            'is_saving': False,
        }
        return context


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
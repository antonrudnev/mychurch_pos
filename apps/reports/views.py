from decimal import Decimal
from urllib.parse import urlencode

from directory.models import Item
from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import (
    Case,
    CharField,
    DecimalField,
    ExpressionWrapper,
    F,
    Q,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce, StrIndex, Substr
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.generic import ListView, TemplateView, View
from transactions.models import Transaction
from weasyprint import CSS, HTML

from .forms import ReportDateRangeForm, ReportNameForm
from .models import Report, ReportType


def render_cash_report_document(html, base_url):
    base_stylesheet = CSS(string="""
        @page { size: A4 portrait; margin: 10mm; }
        html, body { height: auto !important; margin: 0 !important; color: black !important; }
        .report-page { display: block !important; height: auto !important; min-height: 0 !important; }
        h2 { margin: 0 0 4mm !important; font-size: 12pt !important; }
        h5 { font-size: 7pt !important; margin-bottom: 10px; }
        table {
            flex: 1 1 0; height: 0; min-height: 0; margin: 0 0 6mm; box-shadow: none;
        }
        tbody { height: auto !important; }
        tr { break-inside: avoid; }
        td {
            padding: 2.2mm 2mm !important;
            line-height: 1.4 !important;
            color: black !important;
        }
        .name-cell-tall { height: 100px !important; }
        .report-footer { margin: 0 !important; font-size: 8pt !important; }
        .report-actions, .alert-success { display: none !important; }
    """)

    def render_at_font_size(font_size):
        font_stylesheet = CSS(string=f'table, table td {{ font-size: {font_size}pt !important; }}')
        return HTML(string=html, base_url=base_url).render(
            stylesheets=[base_stylesheet, font_stylesheet],
        )

    font_size = 8.0
    document = render_at_font_size(font_size)

    return document, font_size


class CashReportView(PermissionRequiredMixin, TemplateView):
    template_name = 'reports/report_date_range.html'
    permission_required = 'reports.add_report'
    raise_exception = False

    def get(self, request, *args, **kwargs):
        if request.GET.get('select_period') == '1':
            date_from = parse_date(request.GET.get('date_from', ''))
            date_to = parse_date(request.GET.get('date_to', ''))
            initial = {}
            if date_from:
                initial['date_from'] = date_from
            if date_to:
                initial['date_to'] = date_to
            preset = request.GET.get('preset', 'custom')
            if preset not in {'week', 'last-week', '3', '5', 'custom'}:
                preset = 'custom'
            return self.render_to_response({
                'form': ReportDateRangeForm(initial=initial),
                'application_today': timezone.localdate(),
                'selected_preset': preset,
                'preserve_date_values': request.GET.get('preserve_dates') == '1',
            })

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

        date_from = form.cleaned_data['date_from']
        date_to = form.cleaned_data['date_to']
        can_skip_unverified_check = (
            request.GET.get('skip_unverified_check') == '1'
            and request.user.has_perm('transactions.verify_transaction')
        )
        has_unverified = (
            not can_skip_unverified_check
            and Transaction.objects.filter(
                is_deleted=False,
                is_verified=False,
                created_at__date__range=(date_from, date_to),
            ).exists()
        )
        if has_unverified:
            return redirect(
                self.get_unverified_review_url(
                    date_from,
                    date_to,
                    request.GET.get('preset', 'custom'),
                )
            )

        self.template_name = 'reports/cash_report.html'
        return self.render_to_response(self.get_report_context(form))

    def post(self, request, *args, **kwargs):
        form = ReportDateRangeForm(request.POST)
        if not form.is_valid():
            return self.render_to_response({'form': form}, status=400)

        date_from = form.cleaned_data['date_from']
        date_to = form.cleaned_data['date_to']
        self.template_name = 'reports/cash_report.html'
        context = self.get_report_context(form)
        context['is_saving'] = True
        html_dump = render_to_string(self.template_name, context, request=request)

        report_name = (
            f"Кассовый отчет за {date_from:%d.%m.%Y}{f' - {date_to:%d.%m.%Y}' if date_from != date_to else ''}"
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
        return redirect('reports:home')

    def get_unverified_review_url(self, date_from, date_to, preset='custom'):
        if preset not in {'week', 'last-week', '3', '5', 'custom'}:
            preset = 'custom'
        query = urlencode({
            'unverified': '1',
            'date_from': date_from.isoformat(),
            'date_to': date_to.isoformat(),
            'preset': preset,
        })
        return f"{reverse('transactions:transaction_list')}?{query}"

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
        product_total = (
            Transaction.objects
            .filter(
                item__item_type__is_product_group=True,
                is_deleted=False,
                created_at__date__range=date_range,
            )
            .aggregate(total_cost=Sum(F('quantity') * F('price')))
            .get('total_cost')
        )

        prefix = "candle"
        candle_total= (
            Transaction.objects
            .filter(
                item__item_type__handle__istartswith=prefix,
                is_deleted=False,
                created_at__date__range=date_range,
            )
            .aggregate(total_cost=Sum(F('quantity') * F('price')))
            .get('total_cost')
        )

        prefix = "debt-lend"
        debt_lend_total = (
            Transaction.objects
            .filter(
                item__handle__iexact=prefix,
                is_deleted=False,
                created_at__date__range=date_range,
            )
            .aggregate(total_cost=Sum('price'))
            .get('total_cost')
        )

        prefix = "debt-repay"
        debt_repay_total = (
            Transaction.objects
            .filter(
                item__handle__iexact=prefix,
                is_deleted=False,
                created_at__date__range=date_range,
            )
            .aggregate(total_cost=Sum('price'))
            .get('total_cost')
        )

        prefix = "bank-terminal"
        bank_terminal_total = (
        Transaction.objects
        .filter(
            item__handle__iexact=prefix,
            is_deleted=False,
            created_at__date__range=date_range,
                )
                .aggregate(total_cost=Sum('price'))
                .get('total_cost')
            )

        prefix = "bank-receipt"
        bank_receipt_total = (
            Transaction.objects
            .filter(
                item__handle__iexact=prefix,
                is_deleted=False,
                created_at__date__range=date_range,
            )
            .aggregate(total_cost=Sum('price'))
            .get('total_cost')
        )

        prefix = "cash-register"
        cash_register_last = (
            Transaction.objects
            .filter(
                item__handle__iexact=prefix,
                is_deleted=False,
                created_at__date__range=date_range,
            )
            .order_by('-created_at')
            .first()
        )

        prefix = "cash-deposit"
        cash_deposit_last = (
            Transaction.objects
            .filter(
                item__handle__iexact=prefix,
                is_deleted=False,
                created_at__date__range=date_range,
            )
            .order_by('-created_at')
            .first()
        )

        prefix = "staff"
        staff_total = (
            Transaction.objects
            .filter(
                item__item_type__handle__iexact=prefix,
                is_deleted=False,
                created_at__date__range=date_range,
            )
            .aggregate(total_cost=Sum(F('quantity') * F('price')))
            .get('total_cost')
        )
        staff_data = (
            Item.objects
            .filter(item_type__handle__iexact=prefix)
            .annotate(
                first_dash=StrIndex('handle', Value('-')),
                second_dash_in_tail=Case(
                    When(first_dash__gt=0, then=StrIndex(Substr('handle', F('first_dash') + 1), Value('-'))),
                    default=0
                ),
                second_dash=Case(
                    When(second_dash_in_tail__gt=0, then=F('first_dash') + F('second_dash_in_tail')),
                    default=0
                ),
                short_handle=Case(
                    When(second_dash__gt=0, then=Substr('handle', 1, F('second_dash') - 1)),
                    default=F('handle'),
                    output_field=CharField()
                )
            )
            .values('short_handle')
            .annotate(
                total_cost=Coalesce(
                    Sum(
                        ExpressionWrapper(
                            F('transactions__quantity') * F('transactions__price'),
                            output_field=DecimalField(max_digits=20, decimal_places=2),
                        ),
                        filter=Q(
                            transactions__is_deleted=False,
                            transactions__created_at__date__range=date_range,
                        ),
                    ),
                    Value(
                        Decimal('0.00'),
                        output_field=DecimalField(max_digits=20, decimal_places=2),
                    ),
                    output_field=DecimalField(max_digits=20, decimal_places=2),
                )
            )
            .order_by('short_handle')
        )

        prefix = "donate"
        donate_total = (
            Transaction.objects
            .filter(
                item__item_type__handle__iexact=prefix,
                is_deleted=False,
                created_at__date__range=date_range,
            )
            .aggregate(total_cost=Sum('price'))
            .get('total_cost')
        )
        donate_data = (
            Transaction.objects
            .filter(
                item__item_type__handle__iexact=prefix,
                is_deleted=False,
                created_at__date__range=date_range,
            )
            .values('item__name',
                    'item__handle')
            .annotate(total_cost=Sum('price'))
            .order_by('item__handle')
        )

        prefix = "other-treby"
        other_treby_data = (
            Transaction.objects
            .filter(
                item__item_type__handle__iexact=prefix,
                is_deleted=False,
                created_at__date__range=date_range,
            )
            .values('item__name',
                    'item__handle')
            .annotate(total_cost=Sum('price'))
            .order_by('item__name')
        )

        prefix = "other-expense"
        other_expense_data = (
            Transaction.objects
            .filter(
                item__item_type__handle__iexact=prefix,
                is_deleted=False,
                created_at__date__range=date_range,
            )
            .values('item__name',
                    'item__handle')
            .annotate(total_cost=Sum('price'))
            .order_by('item__name')
        )

        bank_terminal_sales = bank_terminal_total - donate_total if bank_terminal_total and donate_total else 0

        not_verified_status = (
            Transaction.objects
            .filter(
                is_deleted=False,
                is_verified=False,
                created_at__date__range=date_range,
            )
            .count()
        )

        context = {
            'treby_data': treby_data,
            'product_total': product_total,
            'candle_total': candle_total,
            'debt_lend_total': debt_lend_total,
            'debt_repay_total': debt_repay_total,
            'bank_terminal_total': bank_terminal_total,
            'bank_terminal_sales': bank_terminal_sales,
            'bank_receipt_total': bank_receipt_total,
            'staff_total': staff_total,
            'staff_data': staff_data,
            'cash_register_last': cash_register_last,
            'cash_deposit_last': cash_deposit_last,
            'donate_total': donate_total,
            'donate_data': donate_data,
            'other_treby_data': other_treby_data,
            'other_expense_data': other_expense_data,
            'not_verified_status':not_verified_status,
            'unverified_review_url': self.get_unverified_review_url(
                date_from,
                date_to,
            ),
            'current_time': timezone.now(),
            'current_user': self.request.user,
            'date_from': date_from,
            'date_to': date_to,
            'is_saving': False,
        }
        return context


class CashReportPdfView(CashReportView):
    def get(self, request, *args, **kwargs):
        form = ReportDateRangeForm(request.GET)
        if not form.is_valid():
            return self.render_to_response(
                {'form': form, 'application_today': timezone.localdate()},
                status=400,
            )

        context = self.get_report_context(form)
        context['is_saving'] = True
        html = render_to_string(
            'reports/cash_report.html',
            context,
            request=request,
        )
        document, _font_size = render_cash_report_document(
            html,
            base_url=request.build_absolute_uri('/'),
        )
        pdf = document.write_pdf()
        response = HttpResponse(pdf, content_type='application/pdf')
        date_from = form.cleaned_data['date_from']
        date_to = form.cleaned_data['date_to']
        filename = f'cash-report-{date_from:%Y-%m-%d}-{date_to:%Y-%m-%d}.pdf'
        response['Content-Disposition'] = f'inline; filename="{filename}"'
        return response


class PrintReportView(PermissionRequiredMixin, View):
    permission_required = 'reports.view_report'
    raise_exception = True 

    def get(self, request, report_id, *args, **kwargs):
        report = get_object_or_404(Report, id=report_id)
        if request.GET.get('format') == 'pdf':
            document, _font_size = render_cash_report_document(
                report.dump,
                base_url=request.build_absolute_uri('/'),
            )
            response = HttpResponse(
                document.write_pdf(),
                content_type='application/pdf',
            )
            response['Content-Disposition'] = (
                f'inline; filename="report-{report.pk}.pdf"'
            )
            return response
        return HttpResponse(report.dump, content_type='text/html; charset=utf-8')


class ReportManageView(PermissionRequiredMixin, View):
    permission_required = ('reports.change_report', 'reports.delete_report')
    raise_exception = True
    template_name = 'reports/report_manage.html'

    def has_permission(self):
        return any(
            self.request.user.has_perm(permission)
            for permission in self.get_permission_required()
        )

    def get_report(self, report_id):
        return get_object_or_404(Report, id=report_id)

    def get(self, request, report_id, *args, **kwargs):
        report = self.get_report(report_id)
        return self.render_page(request, report, ReportNameForm(initial={'name': report.name}))

    def post(self, request, report_id, *args, **kwargs):
        report = self.get_report(report_id)
        action = request.POST.get('action')

        if action == 'rename':
            if not request.user.has_perm('reports.change_report'):
                raise PermissionDenied
            form = ReportNameForm(request.POST)
            if not form.is_valid():
                return self.render_page(request, report, form, status=400)
            report.name = form.cleaned_data['name']
            report.save(update_fields=['name'])
            messages.success(request, 'Название отчета изменено.')
            return redirect('reports:home')

        if action == 'delete':
            if not request.user.has_perm('reports.delete_report'):
                raise PermissionDenied
            report.delete()
            messages.success(request, 'Отчет удален.')
            return redirect('reports:home')

        raise PermissionDenied

    def render_page(self, request, report, form, status=200):
        return render(
            request,
            self.template_name,
            {
                'report': report,
                'form': form,
            },
            status=status,
        )


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
        return redirect('reports:home')


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
from django.urls import path

from .views import (
    CashReportPrintView,
    DynamicReportRouterView,
    ProductReportPrintView,
    ReportManageView,
    ReportListView,
    SavedReportPrintView,
    ReportTypeSelectView,
)

app_name = 'reports'

urlpatterns = [
    path('', ReportListView.as_view(), name='home'),
    path('new/', ReportTypeSelectView.as_view(), name='report_type_select'),
    path(
        'generate/<str:handle_key>/',
        DynamicReportRouterView.as_view(),
        name='generate_report',
    ),
    path(
        'generate/cash-report/pdf/',
        CashReportPrintView.as_view(),
        name='cash_report_pdf',
    ),
    path(
        'generate/product-report/pdf/',
        ProductReportPrintView.as_view(),
        name='product_report_pdf',
    ),
    path(
        '<int:report_id>/',
        ReportManageView.as_view(),
        name='manage_report',
    ),
    path(
        '<int:report_id>/print/',
        SavedReportPrintView.as_view(),
        name='print_report',
    ),
]

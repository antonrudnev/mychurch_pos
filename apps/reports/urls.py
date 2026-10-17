from django.urls import path

from .views import CashReportView, PrintReportView, ReportListView

app_name = 'reports'

urlpatterns = [
    # Этот путь отвечает за часть адреса после /reports/
    path('', ReportListView.as_view(), name='report_list'),
    path('cash/', CashReportView.as_view(), name='cash_report'),
    path('<int:report_id>/print/', PrintReportView.as_view(), name='print_report'),
]

from django.urls import path

from .views import CashReportView, print_report_view

app_name = 'reports'

urlpatterns = [
    # Этот путь отвечает за часть адреса после /reports/
    path('cash/', CashReportView.as_view(), name='cash_report'),
    path('<int:report_id>/print/', print_report_view, name='print_report'),
]

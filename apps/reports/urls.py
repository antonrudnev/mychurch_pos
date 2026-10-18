from django.urls import path

from .views import (
    DynamicReportRouterView,
    PrintReportView,
    ReportManageView,
    ReportListView,
    ReportTypeSelectView,
)

app_name = 'reports'

urlpatterns = [
    # Этот путь отвечает за часть адреса после /reports/
    path('', ReportListView.as_view(), name='report_list'),
    path('new/', ReportTypeSelectView.as_view(), name='report_type_select'),
    path('generate/<str:handle_key>/', DynamicReportRouterView.as_view(), name='generate_report'),
    path('<int:report_id>/', ReportManageView.as_view(), name='manage_report'),
    path('<int:report_id>/print/', PrintReportView.as_view(), name='print_report'),
]

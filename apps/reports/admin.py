from django.contrib import admin
from django.urls import reverse
from django.utils.safestring import mark_safe

from .models import Report, ReportType


@admin.register(ReportType)
class ReportTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'handle')
    prepopulated_fields = {'handle': ('name',)}
    

@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ('name', 'report_type', 'created_at', 'created_by', 'view_report_link')
    list_filter = ('report_type','created_at', 'created_by')    
    readonly_fields = ('report_type', 'dump', 'created_at', 'created_by',)

    def get_readonly_fields(self, request, obj=None):
        if obj: 
            return ('report_type', 'created_at', 'created_by', 'dump')

        return ('created_at', 'created_by',)

    @admin.display(description="Просмотр")
    def view_report_link(self, obj):
        url = reverse('reports:print_report', args=[obj.id])

        return mark_safe(f'<a href="{url}" target="_blank">Открыть</a>')

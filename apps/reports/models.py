from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class ReportType(models.Model):
    name = models.CharField(
        max_length=255,
        unique=True,
        verbose_name="Название типа отчета")
    handle = models.SlugField(
        max_length=100, 
        unique=True, 
        verbose_name="Дескриптор",
        help_text="Системный идентификатор. Изменение параметра может нарушить логику обработки данных.",
    )

    class Meta:
        verbose_name = "Тип отчета"
        verbose_name_plural = "Типы отчетов"

    def __str__(self):
        return self.name

class Report(models.Model):
    name = models.CharField(
        max_length=255, 
        verbose_name="Название отчета"
    )
    report_type = models.ForeignKey(
        ReportType,
        on_delete=models.PROTECT,
        related_name="reports",
        verbose_name="Тип отчета",
    )
    created_at = models.DateTimeField(
        auto_now_add=True, 
        verbose_name="Дата и время создания"
    )
    dump = models.TextField(
        verbose_name="HTML дамп страницы"
    )
    created_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        verbose_name="Сформировал"
    )
    
    class Meta:
        verbose_name = "Отчет"
        verbose_name_plural = "Отчеты"
        ordering = ['-created_at']  # Свежие отчеты будут вверху

    def __str__(self):
        created_at = timezone.localtime(self.created_at)
        return f"{self.name} от {created_at.strftime('%d.%m.%Y %H:%M')}"
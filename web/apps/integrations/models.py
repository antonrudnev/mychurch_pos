from django.db import models


class DocumentType(models.TextChoices):
    """Supported report types for Dropbox documents."""

    PRODUCT_REPORT = "product_report", "Товарная ведомость"
    CANDLE_REPORT = "candle_report", "Свечная ведомость"


class DocumentSyncState(models.Model):
    """Persist Dropbox synchronization settings and the latest sync outcome."""

    folder_path = models.CharField(
        max_length=512,
        unique=True,
        verbose_name="Путь к папке Dropbox",
        help_text="Путь к папке Dropbox для синхронизации.",
    )
    document_type = models.CharField(
        max_length=50,
        choices=DocumentType.choices,
        db_index=True,
        verbose_name="Тип документа",
        help_text="Тип отчета, связанный с этой папкой Dropbox.",
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Активна",
        help_text="Включена ли синхронизация этой папки Dropbox.",
    )
    cursor = models.TextField(
        null=True,
        blank=True,
        verbose_name="Курсор Dropbox",
        help_text="Курсор Dropbox ListFolder для инкрементальной синхронизации.",
    )
    last_synced_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Последняя успешная синхронизация",
        help_text="Дата и время последнего успешного завершения синхронизации.",
    )
    last_error = models.TextField(
        default="",
        blank=True,
        verbose_name="Последняя ошибка синхронизации",
        help_text="Описание последней ошибки синхронизации, если она возникла.",
    )

    class Meta:
        verbose_name = "Dropbox синхронизация "
        verbose_name_plural = "Dropbox синхронизация"

    def __str__(self) -> str:
        return f"{self.get_document_type_display()}: {self.folder_path}"


class IncomingDocument(models.Model):
    """Track Dropbox files downloaded for processing by the application."""

    class Status(models.TextChoices):
        DOWNLOADED = "downloaded", "Загружен"
        PROCESSING = "processing", "Обрабатывается"
        PROCESSED = "processed", "Обработан"
        ERROR = "error", "Ошибка"
        DELETED = "deleted", "Удален"

    document_type = models.CharField(
        max_length=50,
        choices=DocumentType.choices,
        db_index=True,
        verbose_name="Тип документа",
        help_text="Тип отчета, связанный с этим документом Dropbox.",
    )
    dropbox_file_id = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        verbose_name="ID файла Dropbox",
        help_text="Уникальный идентификатор файла, присвоенный Dropbox.",
    )
    content_hash = models.CharField(
        max_length=64,
        blank=True,
        default="",
        verbose_name="Хэш содержимого",
        help_text="Хэш SHA-256 содержимого, указанный Dropbox.",
    )
    original_name = models.CharField(
        max_length=255,
        verbose_name="Исходное имя файла",
        help_text="Исходное имя документа в Dropbox.",
    )
    dropbox_path = models.CharField(
        max_length=1024,
        verbose_name="Путь в Dropbox",
        help_text="Полный отображаемый путь к файлу в Dropbox.",
    )
    local_file = models.FileField(
        upload_to="dropbox/",
        max_length=1024,
        verbose_name="Локальный файл",
        help_text="Путь к загруженному файлу относительно MEDIA_ROOT.",
    )
    file_size = models.BigIntegerField(
        default=0,
        verbose_name="Размер файла",
        help_text="Размер загруженного файла в байтах.",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        db_index=True,
        default=Status.DOWNLOADED,
        verbose_name="Статус",
        help_text="Текущий статус загрузки и обработки документа.",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Дата создания",
        help_text="Дата и время создания записи в UTC.",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Входящий документ"
        verbose_name_plural = "Входящие документы"

    def __str__(self) -> str:
        return (f"[{self.get_document_type_display()}] {self.original_name}")

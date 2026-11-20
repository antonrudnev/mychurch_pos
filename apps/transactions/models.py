from directory.models import Item
from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

User = get_user_model()


class DocumentType(models.TextChoices):
    """Supported report types for Dropbox documents."""

    PRODUCT_REPORT = "product_report", "Товарная ведомость"
    CANDLE_REPORT = "candle_report", "Свечная ведомость"


class TransactionQuerySet(models.QuerySet):
    """Кастомный QuerySet для автоматической фильтрации удаленных записей"""
    def active(self):
        return self.filter(is_deleted=False)


class TransactionManager(models.Manager):
    """Менеджер модели, который по умолчанию возвращает только живые транзакции"""
    def get_queryset(self):
        return TransactionQuerySet(self.model, using=self._db).active()
        
    def all_with_deleted(self):
        """Метод для получения абсолютно всех записей, включая удаленные"""
        return TransactionQuerySet(self.model, using=self._db)


class Transaction(models.Model):
    """Единый журнал транзакций """    
    item = models.ForeignKey(
        Item, 
        on_delete=models.PROTECT, 
        related_name='transactions',
        verbose_name="Наименование"
    )
    price = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        validators=[MinValueValidator(0)],
        verbose_name="Сумма"
    )
    quantity = models.PositiveIntegerField(
        default=1, 
        validators=[MinValueValidator(1)],
        verbose_name="Количество"
    )
    cashier = models.ForeignKey(
            User, 
            on_delete=models.PROTECT, 
            related_name='transactions',
            verbose_name="Кассир"
    )
    created_at = models.DateTimeField(
        default=timezone.now, 
        verbose_name="Дата и время"
    )
    is_verified = models.BooleanField(
        default=False, 
        verbose_name="Проверено",
        help_text="Флаг подтверждения корректности операции аудитором"
    )
    verified_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_transactions',
        verbose_name="Аудитор"
    )
    is_deleted = models.BooleanField(
        default=False, 
        verbose_name="Удалено в корзину"
    )

    # Подключаем кастомные менеджеры
    objects = TransactionManager()

    class Meta:
        verbose_name = "Транзакция"
        verbose_name_plural = "Список транзакций"
        ordering = ('-created_at',)

        permissions = [
            ("view_all_transactions", f"Can view {verbose_name} of all users"),
            ("verify_transaction", f"Can verify {verbose_name}"),
        ]

    @property
    def total_cost(self):
        """Динамический расчет стоимости без сохранения в базу данных"""
        return self.price * self.quantity if self.price and self.quantity else 0

    def delete_soft(self, *args, **kwargs):
        self.is_deleted = True
        self.save()

    def save(self, *args, **kwargs):
        if self.price is None and self.item:
            self.price = self.item.price
        super().save(*args, **kwargs)

    def __str__(self):
        status = " [Удалено]" if self.is_deleted else ""
        created_at = timezone.localtime(self.created_at)
        total = f'{self.total_cost} руб.' if self.total_cost > 0 else f'{self.quantity} шт.'
        return f"{created_at.strftime('%d.%m.%Y %H:%M')} — {self.item.name} ({total}){status}"


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
        db_table = "transactions_document_sync_state"
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
        db_table = "transactions_incoming_document"
        ordering = ["-created_at"]
        verbose_name = "Входящий документ"
        verbose_name_plural = "Входящие документы"

    def __str__(self) -> str:
        return (
            f"{self.get_document_type_display()}: "
            f"{self.original_name} ({self.get_status_display()})"
        )

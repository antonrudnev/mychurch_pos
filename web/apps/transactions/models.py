from directory.models import Item
from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from integrations.models import IncomingDocument

User = get_user_model()


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


class IncomingTransaction(models.Model):
    """Буферная таблица распознанных позиций из сканов документов до проверки оператором."""

    document = models.ForeignKey(
        IncomingDocument,
        on_delete=models.CASCADE,
        related_name="incoming_transactions",
        verbose_name="Документ",
    )
    report_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Дата документа",
        help_text="Дата операции из документа, с которой транзакция попадёт в основной журнал",
    )
    row_number = models.PositiveIntegerField(
        default=1,
        verbose_name="Номер строки",
        help_text="Порядковый номер строки в исходном документе",
    )
    item = models.ForeignKey(
        Item,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="incoming_transactions",
        verbose_name="Название из справочника",
    )
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        verbose_name="Цена",
    )
    quantity = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        verbose_name="Количество",
    )
    raw_name = models.CharField(
            max_length=255,
            blank=True,
            default="",
            verbose_name="Распознанное название",
        )
    raw_counts = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Ряд количеств",
        help_text="Список отдельных чисел продаж из строки (например, [2, 10, 3])",
    )
    transaction = models.OneToOneField(
        Transaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="incoming_source",
        verbose_name="Созданная транзакция",
        help_text="Если заполнено - строка уже проведена в основной журнал транзакций",
    )
    processed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="processed_incoming_transactions",
        verbose_name="Проверил оператор",
    )
    is_deleted = models.BooleanField(
        default=False,
        verbose_name="Удалено в корзину",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Дата загрузки",
    )

    objects = TransactionManager()

    class Meta:
        verbose_name = "Входящая транзакция"
        verbose_name_plural = "Входящие транзакции"
        ordering = ("document", "row_number")

    @property
    def total_cost(self):
        return self.price * self.quantity if self.price is not None and self.quantity else 0

    @property
    def is_matched(self) -> bool:
        """Сопоставлена ли строка с реальным товаром из справочника"""
        return self.item_id is not None

    @property
    def is_processed(self) -> bool:
        """Проведена ли строка в основной журнал Transaction"""
        return self.transaction_id is not None

    def delete_soft(self, *args, **kwargs):
        self.is_deleted = True
        self.save()

    def __str__(self):
        status = " [Удалено]" if self.is_deleted else (" [Проведено]" if self.is_processed else "")
        title = self.item.name if self.item else f"[Не найден: {self.raw_name or self.raw_handle}]"
        return f"Док #{self.document_id} (стр. {self.row_number}) — {title} × {self.quantity} = {self.total_cost} руб.{status}"


from decimal import Decimal

from directory.models import Item
from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator
from django.db import models

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
    cashier = models.ForeignKey(
        User, 
        on_delete=models.PROTECT, 
        related_name='transactions',
        verbose_name="Кассир"
    )
    item = models.ForeignKey(
        Item, 
        on_delete=models.PROTECT, 
        related_name='transactions',
        verbose_name="Товар / Услуга"
    )
    price = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        validators=[MinValueValidator(Decimal('0.00'))],
        verbose_name="Цена за единицу"
    )
    quantity = models.PositiveIntegerField(
        default=1, 
        verbose_name="Количество"
    )
    is_cashless = models.BooleanField(
        default=False,
        verbose_name="Безналичный расчет",
        help_text="Отметьте, если оплата прошла по карте, терминалу или QR-коду"
    )
    created_at = models.DateTimeField(
        auto_now_add=True, 
        verbose_name="Дата и время"
    )
    is_verified = models.BooleanField(
        default=False, 
        verbose_name="Проверено аудитором",
        help_text="Флаг подтверждения корректности операции"
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

    @property
    def total_cost(self):
        """Динамический расчет стоимости без сохранения в базу данных"""
        return self.price * self.quantity if self.price and self.quantity else 0

    def delete(self, *args, **kwargs):
        """Переопределение метода удаления для реализации soft-delete"""
        self.is_deleted = True
        self.save()

    def save(self, *args, **kwargs):
        if not self.price and self.item:
            self.price = self.item.price
        super().save(*args, **kwargs)

    def __str__(self):
        status = " [Удалено]" if self.is_deleted else ""
        payment = " (Безнал)" if self.is_cashless else "(Наличные)"
        return f"{self.created_at.strftime('%d.%m.%Y %H:%M')} — {self.item.name} ({self.quantity} шт.){payment}{status}"

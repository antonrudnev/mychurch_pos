from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models


class ItemType(models.Model):
    """Таблица типов номенклатуры (например: Товар, Таинство, Записка, Пожертвование)"""
    name = models.CharField(
        max_length=100, 
        unique=True, 
        verbose_name="Название категории"
    )
    slug = models.SlugField(
        max_length=100, 
        unique=True, 
        verbose_name="Дескриптор"
    )

    class Meta:
        verbose_name = "Категория номенклатуры"
        verbose_name_plural = "Категории номенклатуры"
        ordering = ('name',)

    def __str__(self):
        return self.name


class Item(models.Model):
    """Единый реестр товаров и услуг церковной лавки"""
    item_type = models.ForeignKey(
        ItemType, 
        on_delete=models.PROTECT, 
        related_name='items', 
        verbose_name="Категория"
    )
    name = models.CharField(max_length=255, verbose_name="Название")
    price = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.00'))],
        verbose_name="Цена / Рекомендуемый взнос"
    )
    is_active = models.BooleanField(
        default=True, 
        verbose_name="Активен"
    )
    created_at = models.DateTimeField(
        auto_now_add=True, 
        verbose_name="Дата добавления"
    )

    class Meta:
        verbose_name = "Позиция реестра"
        verbose_name_plural = "Реестр товаров и услуг"
        ordering = ('item_type__name', 'name')

    def __str__(self):
        price = f"{self.price} руб." if self.price is not None else "Цена не указана"
        return f"[{self.item_type.name}] {self.name} ({price})"
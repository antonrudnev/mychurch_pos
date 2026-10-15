from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models.aggregates import Max


class ItemType(models.Model):
    """Таблица типов номенклатуры (например: Товар, Таинство, Записка, Пожертвование)"""
    name = models.CharField(
        max_length=100, 
        unique=True, 
        verbose_name="Название категории"
    )
    handle = models.SlugField(
        max_length=100, 
        unique=True, 
        verbose_name="Дескриптор"
    )
    order = models.PositiveIntegerField(
        default=1, 
        validators=[MinValueValidator(1)],
        verbose_name="Порядок сортировки"
    )
    is_product_group = models.BooleanField(
        default=False, 
        verbose_name="Товарная группа",
        help_text="Флаг, указывающий, что данная категория образует группу ''Товары''"
    )

    class Meta:
        verbose_name = "Категория номенклатуры"
        verbose_name_plural = "Категории номенклатуры"
        ordering = ('name',)

    def save(self, *args, **kwargs):
        if not self.pk and self.order == 1:
            max_order = ItemType.objects.aggregate(max_val=Max('order'))['max_val']
            if max_order is not None:
                self.order = max_order + 1
                
        super().save(*args, **kwargs)
    
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
    name = models.CharField(
        max_length=255,
        verbose_name="Название"
    )
    handle = models.SlugField(
            max_length=100, 
            unique=True, 
            verbose_name="Артикул"
    )
    price = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.00'))],
        verbose_name="Цена / Рекомендуемый взнос",
        help_text="Оставьте пустым, если цена не предусмотрена"
    )
    order = models.PositiveIntegerField(
        default=1, 
        validators=[MinValueValidator(1)],
        verbose_name="Порядок сортировки"
    )
    is_active = models.BooleanField(
        default=True, 
        verbose_name="Активен",
        help_text="Флаг, указывающий, что товар/услуга доступна для продажи"
    )

    class Meta:
        verbose_name = "Позиция реестра"
        verbose_name_plural = "Реестр товаров и услуг"
        ordering = ('item_type__name', 'name')

    def save(self, *args, **kwargs):
        if not self.pk and self.order == 1:
            max_order = Item.objects.aggregate(max_val=Max('order'))['max_val']
            if max_order is not None:
                self.order = max_order + 1
                
        super().save(*args, **kwargs)
        
    def __str__(self):
        price = f"{self.price} руб." if self.price is not None else "Цена не указана"
        return f"[{self.item_type.name}] {self.name} ({price})"
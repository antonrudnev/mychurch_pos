from django.db import models


class ItemType(models.Model):
    """Таблица типов номенклатуры (например: Товар, Таинство, Записка, Пожертвование)"""
    name = models.CharField(max_length=100, unique=True, verbose_name="Название типа")
    slug = models.SlugField(max_length=100, unique=True, verbose_name="Идентификатор для кода")
    has_stock = models.BooleanField(
        default=False, 
        verbose_name="Учитывать остатки на складе",
        help_text="Включите для физических товаров, выключите для услуг и треб"
    )

    class Meta:
        verbose_name = "Тип номенклатуры"
        verbose_name_plural = "Типы номенклатуры"
        ordering = ('name',)

    def __str__(self):
        return self.name


class Item(models.Model):
    """Единый реестр товаров и услуг церковной лавки"""
    item_type = models.ForeignKey(
        ItemType, 
        on_delete=models.PROTECT, 
        related_name='items', 
        verbose_name="Тип"
    )
    name = models.CharField(max_length=255, verbose_name="Название")
    price = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        verbose_name="Цена / Рекомендуемый взнос"
    )
    stock = models.PositiveIntegerField(
        default=0, 
        verbose_name="Остаток на складе",
        help_text="Используется, если у типа включен учёт остатков"
    )
    is_active = models.BooleanField(default=True, verbose_name="Активен")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата добавления")

    class Meta:
        verbose_name = "Позиция реестра"
        verbose_name_plural = "Реестр товаров и услуг"
        ordering = ('item_type__name', 'name')

    def __str__(self):
        return f"[{self.item_type.name}] {self.name} ({self.price} руб.)"
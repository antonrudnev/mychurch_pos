from decimal import Decimal

from directory.models import Item, ItemType
from django import forms
from django.core.validators import MinValueValidator
from django.utils import timezone

from .models import Transaction

DATE_FIELD_ITEM_HANDLES = ('bank-receipt',)
TRANSACTION_DATETIME_FORMAT = '%Y-%m-%dT%H:%M'


def transaction_datetime_widget():
    return forms.DateTimeInput(
        attrs={'type': 'hidden'},
        format=TRANSACTION_DATETIME_FORMAT,
    )


class NewProductTransactionForm(forms.Form):
    name = forms.CharField(
        label='Название товара',
        max_length=255,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    price = forms.DecimalField(
        label='Цена за единицу',
        max_digits=10,
        decimal_places=2,
        min_value=Decimal('0.01'),
        validators=[MinValueValidator(Decimal('0.01'))],
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'min': '0.01',
            'step': '0.01',
        }),
    )
    quantity = forms.IntegerField(
        label='Количество',
        min_value=1,
        initial=1,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'min': '1',
        }),
    )
    keep_active = forms.BooleanField(
        label='Оставить товар активным в справочнике',
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        if not name:
            raise forms.ValidationError('Введите название товара.')
        return name


class NewOpenListItemForm(forms.Form):
    name = forms.CharField(
        label='Название статьи',
        max_length=255,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'list': 'recent-item-names',
            'autocomplete': 'off',
        }),
    )
    price = forms.DecimalField(
        label='Стоимость',
        max_digits=10,
        decimal_places=2,
        min_value=Decimal('0.01'),
        validators=[MinValueValidator(Decimal('0.01'))],
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'min': '0.01',
            'step': '0.01',
        }),
    )

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        if not name:
            raise forms.ValidationError('Введите наименование.')
        return name


class TransactionManageForm(forms.ModelForm):
    created_at = forms.DateTimeField(
        label='Дата и время',
        input_formats=[TRANSACTION_DATETIME_FORMAT],
        widget=forms.DateTimeInput(
            attrs={
                'class': 'form-control text-end',
                'type': 'datetime-local',
                'lang': 'ru',
            },
            format=TRANSACTION_DATETIME_FORMAT,
        ),
    )

    class Meta:
        model = Transaction
        fields = ('price', 'quantity', 'created_at')
        widgets = {
            'price': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0.00',
                'step': '0.01',
            }),
            'quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        item_price = self.instance.item.price
        if item_price is None:
            self.fields.pop('price')
        elif item_price == 0:
            self.fields.pop('quantity')
        if self.instance.item.handle not in DATE_FIELD_ITEM_HANDLES:
            self.fields.pop('created_at')


class TransactionForm(forms.ModelForm):
    created_at = forms.DateTimeField(
        label='Дата и время',
        required=False,
        initial=timezone.localtime,
        input_formats=[TRANSACTION_DATETIME_FORMAT],
        widget=transaction_datetime_widget(),
    )

    class Meta:
        model = Transaction
        fields = ('item', 'price', 'quantity', 'created_at')
        widgets = {
            'item': forms.Select(attrs={'class': 'form-select'}),
            'price': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0.00',
            }),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
        }

    def __init__(self, *args, item_type: ItemType, selected_item=None, **kwargs):
        super().__init__(*args, **kwargs)
        items = Item.objects.filter(
            item_type=item_type,
            is_active=True,
        ).order_by('order_number', 'name')
        self.fields['item'].queryset = items
        items = list(self.fields['item'].queryset)
        self.fields['item'].label_from_instance = lambda item: item.name
        self.fields['price'].required = False
        self.single_item = items[0] if len(items) == 1 else None
        if selected_item is not None:
            self.fields['item'].initial = selected_item.pk
        elif self.single_item is not None:
            self.fields['item'].initial = self.single_item.pk
        self.item_prices = {
            str(item.pk): str(item.price) if item.price is not None else None
            for item in items
        }
        self.item_handles = {
            str(item.pk): item.handle
            for item in items
        }
        self.date_field_item_handles = DATE_FIELD_ITEM_HANDLES

    def clean(self):
        cleaned_data = super().clean()
        item = cleaned_data.get('item')
        if item is None:
            return cleaned_data

        if item.handle in DATE_FIELD_ITEM_HANDLES:
            if cleaned_data.get('created_at') is None:
                cleaned_data['created_at'] = timezone.now()
        else:
            cleaned_data.pop('created_at', None)

        if item.price is None:
            cleaned_data['price'] = Decimal('0.00')
        elif item.price > 0:
            cleaned_data['price'] = item.price
        elif cleaned_data.get('price') is None or cleaned_data['price'] <= 0:
            self.add_error('price', 'Введите цену больше нуля.')

        return cleaned_data

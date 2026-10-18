from decimal import Decimal

from directory.models import Item, ItemType
from django import forms

from .models import Transaction


class TransactionForm(forms.ModelForm):
    class Meta:
        model = Transaction
        fields = ('item', 'price', 'quantity')
        widgets = {
            'item': forms.Select(attrs={'class': 'form-select'}),
            'price': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '10',
                'min': '0.00',
            }),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
        }

    def __init__(self, *args, item_type: ItemType, **kwargs):
        super().__init__(*args, **kwargs)
        items = Item.objects.filter(
            item_type=item_type,
            is_active=True,
        ).order_by('name')
        self.fields['item'].queryset = items
        self.fields['item'].label_from_instance = lambda item: item.name
        self.fields['price'].required = False
        self.item_prices = {
            str(item.pk): str(item.price) if item.price is not None else None
            for item in items
        }

    def clean(self):
        cleaned_data = super().clean()
        item = cleaned_data.get('item')
        if item is None:
            return cleaned_data

        if item.price is None:
            cleaned_data['price'] = Decimal('0.00')
        elif item.price > 0:
            cleaned_data['price'] = item.price
        elif cleaned_data.get('price') is None or cleaned_data['price'] <= 0:
            self.add_error('price', 'Введите цену больше нуля.')

        return cleaned_data

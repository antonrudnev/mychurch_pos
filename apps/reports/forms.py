from datetime import timedelta

from django import forms
from django.utils import timezone


class ReportDateRangeForm(forms.Form):
    date_from = forms.DateField(
        label="С даты",
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )
    date_to = forms.DateField(
        label="По дату включительно",
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )

    def __init__(self, *args, **kwargs):
        today = timezone.localdate()
        kwargs.setdefault(
            "initial",
            {"date_from": today - timedelta(days=2), "date_to": today},
        )
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        date_from = cleaned_data.get("date_from")
        date_to = cleaned_data.get("date_to")
        if date_from and date_to and date_from > date_to:
            self.add_error("date_to", "Конечная дата не может быть раньше начальной.")
        return cleaned_data


class ReportNameForm(forms.Form):
    name = forms.CharField(
        label="Новое название документа",
        max_length=255,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )

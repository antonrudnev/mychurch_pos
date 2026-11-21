from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError


class CaseInsensitiveUserCreationForm(UserCreationForm):
    def clean_username(self):
        username = super().clean_username()
        user_model = get_user_model()
        username_field = user_model.USERNAME_FIELD

        if user_model._default_manager.filter(
            **{f'{username_field}__iexact': username}
        ).exists():
            raise ValidationError(
                self.fields['username'].error_messages['unique'],
                code='unique',
            )

        return username

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class CaseInsensitiveModelBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        user_model = get_user_model()
        username_field = user_model.USERNAME_FIELD
        username = username or kwargs.get(username_field)

        if username is None or password is None:
            return None

        try:
            user = user_model._default_manager.get(
                **{f'{username_field}__iexact': username}
            )
        except user_model.DoesNotExist:
            user_model().set_password(password)
            return None
        except user_model.MultipleObjectsReturned:
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None

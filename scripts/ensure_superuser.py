import os
import sys
from pathlib import Path

import django

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.contrib.auth import get_user_model


def required_environment_value(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} must be set to create the initial superuser.")
    return value


User = get_user_model()
username = required_environment_value("DJANGO_SUPERUSER_USERNAME")
email = required_environment_value("DJANGO_SUPERUSER_EMAIL")
password = required_environment_value("DJANGO_SUPERUSER_PASSWORD")

try:
    user = User.objects.get(**{User.USERNAME_FIELD: username})
except User.DoesNotExist:
    User.objects.create_superuser(
        **{
            User.USERNAME_FIELD: username,
            "email": email,
            "password": password,
        }
    )
    print(f"Created Django superuser {username!r}.")
else:
    if not user.is_superuser:
        raise RuntimeError(
            f"User {username!r} already exists but is not a superuser."
        )
    print(f"Django superuser {username!r} already exists; leaving it unchanged.")

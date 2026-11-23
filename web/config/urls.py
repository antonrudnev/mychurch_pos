"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from pathlib import Path

from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponseForbidden
from django.urls import include, path, re_path, reverse_lazy
from django.utils._os import safe_join

from config import settings
from config.views import register_view, welcome_landing_view


@login_required
def protected_media(request, path):
    # Проверяем, что пользователь — сотрудник и имеет право просматривать входящие документы
    if not (request.user.is_staff and request.user.has_perm("transactions.view_incomingdocument")):
        return HttpResponseForbidden("You do not have permission to access this file.")

    # Защита от выхода за пределы MEDIA_ROOT (Path Traversal)
    try:
        full_path = Path(safe_join(settings.MEDIA_ROOT, path))
    except ValueError:
        raise Http404("Invalid file path.")

    if not full_path.is_file():
        raise Http404("File not found.")

    return FileResponse(open(full_path, "rb"))


urlpatterns = [
    path('admin/', admin.site.urls),
    path('', welcome_landing_view, name='home'),
    path('welcome/', welcome_landing_view, name='welcome_landing'),
    path('login/', auth_views.LoginView.as_view(redirect_authenticated_user=True), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path(
        'password-change/',
        auth_views.PasswordChangeView.as_view(
            template_name='registration/password_change_form.html',
            success_url=reverse_lazy('password_change_done'),
        ),
        name='password_change',
    ),
    path(
        'password-change/done/',
        auth_views.PasswordChangeDoneView.as_view(
            template_name='registration/password_change_done.html',
        ),
        name='password_change_done',
    ),
    path('register/', register_view, name='register'),
    path('directory/', include('directory.urls')),
    path('integrations/', include('integrations.urls')),
    path('transactions/', include('transactions.urls')),
    path('reports/', include('reports.urls')),
    re_path(r"^media/(?P<path>.*)$", protected_media),
]

admin.site.site_header = "Администрирование церковной лавки"
admin.site.site_title = "Церковная лавка"
admin.site.index_title = "Управление приходом и торговлей"

handler404 = 'config.views.custom_page_not_found_view'
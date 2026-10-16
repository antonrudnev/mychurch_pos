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
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from config.views import register_view, welcome_landing_view

urlpatterns = [
    path('admin/', admin.site.urls),
    path('welcome/', welcome_landing_view, name='welcome_landing'),
    path('login/', auth_views.LoginView.as_view(redirect_authenticated_user=True), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('register/', register_view, name='register'),
    path('reports/', include('reports.urls')),
]

admin.site.site_header = "Администрирование церковной лавки"
admin.site.site_title = "Церковная лавка"
admin.site.index_title = "Управление приходом и торговлей"

handler404 = 'config.views.custom_page_not_found_view'
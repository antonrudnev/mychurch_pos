from django.contrib.auth import login
from django.shortcuts import redirect, render
from integrations.services.azbyka_calendar import get_today_calendar_widget

from config.forms import CaseInsensitiveUserCreationForm


def register_view(request):
    # Если пользователь уже залогинен, отправляем его на главную
    if request.user.is_authenticated:
        return redirect('welcome_landing') 
        
    if request.method == 'POST':
        form = CaseInsensitiveUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            # Автоматически входим в систему после успешной регистрации
            login(request, user)
            return redirect('welcome_landing') 
    else:
        form = CaseInsensitiveUserCreationForm()
        
    return render(request, 'registration/register.html', {'form': form})

def welcome_landing_view(request):
    return render(request, 'welcome/landing.html', {
        "calendar_widget": get_today_calendar_widget(),})

# Обработчик ошибки 404
def custom_page_not_found_view(request, exception):
    # Автоматически перенаправляем на страницу приветствия welcome_landing
    return redirect('welcome_landing')
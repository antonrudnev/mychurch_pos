from django.apps import apps


def global_data(request):
    """Вытаскивает verbose_name напрямую из конфигурации приложения (apps.py)"""
    # Указываем имя приложения 'directory' из его Config-класса
    app_config = apps.get_app_config('directory')
    
    return {
        'directory_app_verbose_name': app_config.verbose_name
    }
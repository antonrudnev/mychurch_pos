from django.conf import settings


def environment(request):
    return {'is_test_environment': settings.TEST_ENVIRONMENT}

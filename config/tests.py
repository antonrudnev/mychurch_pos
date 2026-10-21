from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class CaseInsensitiveUsernameTests(TestCase):
    def test_registration_rejects_username_with_different_case(self):
        get_user_model().objects.create_user(
            username='ChurchUser',
            password='test-password',
        )

        response = self.client.post(
            reverse('register'),
            {
                'username': 'churchuser',
                'password1': 'Another-test-password-123!',
                'password2': 'Another-test-password-123!',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('username', response.context['form'].errors)
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_login_accepts_username_with_different_case(self):
        user = get_user_model().objects.create_user(
            username='ChurchUser',
            password='test-password',
        )

        response = self.client.post(
            reverse('login'),
            {'username': 'churchuser', 'password': 'test-password'},
        )

        self.assertRedirects(response, reverse('welcome_landing'))
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)

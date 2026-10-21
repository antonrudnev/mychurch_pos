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


class PasswordChangeTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='password-user',
            password='Old-password-123!',
        )

    def test_password_change_requires_authentication(self):
        response = self.client.get(reverse('password_change'))

        self.assertRedirects(
            response,
            f'{reverse("login")}?next={reverse("password_change")}',
        )

    def test_password_change_updates_password_and_keeps_user_logged_in(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('password_change'),
            {
                'old_password': 'Old-password-123!',
                'new_password1': 'New-strong-password-456!',
                'new_password2': 'New-strong-password-456!',
            },
        )

        self.assertRedirects(response, reverse('password_change_done'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('New-strong-password-456!'))
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)

import re
import tempfile

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import FileResponse
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.http import content_disposition_header

from .models import DocumentType, IncomingDocument


class IncomingDocumentFileViewTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.TemporaryDirectory()
        self.addCleanup(self.media_root.cleanup)
        settings_override = override_settings(MEDIA_ROOT=self.media_root.name)
        settings_override.enable()
        self.addCleanup(settings_override.disable)

        self.user = get_user_model().objects.create_user(
            username='document-viewer',
            password='test-password',
        )
        self.client.force_login(self.user)
        self.document = IncomingDocument.objects.create(
            document_type=DocumentType.PRODUCT_REPORT,
            dropbox_file_id='incoming-document-file-test',
            original_name='Исходная ведомость.pdf',
            dropbox_path='/reports/Исходная ведомость.pdf',
            local_file=SimpleUploadedFile(
                'Исходная ведомость.pdf',
                b'%PDF-1.4\nsample document\n',
                content_type='application/pdf',
            ),
        )

    def grant_permission(self, codename):
        permission = Permission.objects.get(
            content_type__app_label='integrations',
            codename=codename,
        )
        self.user.user_permissions.add(permission)

    def grant_incoming_page_permission(self):
        permission = Permission.objects.get(
            content_type__app_label='transactions',
            codename='view_incomingtransaction',
        )
        self.user.user_permissions.add(permission)

    def file_url(self):
        return reverse(
            'integrations:incoming_document_file',
            args=[self.document.pk],
        )

    def incoming_page_url(self):
        return reverse(
            'transactions:incoming_document',
            args=[self.document.pk],
        )

    def test_file_requires_permission_and_page_hides_the_file_link(self):
        self.grant_incoming_page_permission()

        page = self.client.get(self.incoming_page_url())
        response = self.client.get(self.file_url())
        self.addCleanup(response.close)

        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, f'href="{self.file_url()}"')
        self.assertEqual(response.status_code, 403)

    def test_authorized_file_is_served_inline_with_utf8_filename(self):
        self.grant_permission('view_incomingdocument')
        self.grant_incoming_page_permission()

        page = self.client.get(self.incoming_page_url())
        response = self.client.get(self.file_url())
        self.addCleanup(response.close)

        self.assertEqual(page.status_code, 200)
        html = page.content.decode()
        link_match = re.search(
            rf'<a\b[^>]*href="{re.escape(self.file_url())}"[^>]*>',
            html,
        )
        self.assertIsNotNone(link_match)
        self.assertIn('target="_blank"', link_match.group())
        self.assertIn('rel="noopener"', link_match.group())
        self.assertNotRegex(link_match.group(), r'\sdownload(?:\s|=|>)')
        self.assertIsInstance(response, FileResponse)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response['Content-Disposition'].startswith('inline;'))
        self.assertEqual(
            response['Content-Disposition'],
            content_disposition_header(
                False,
                self.document.local_file.name.rsplit('/', 1)[-1],
            ),
        )
        self.assertEqual(
            b''.join(response.streaming_content),
            b'%PDF-1.4\nsample document\n',
        )

    def test_missing_or_unattached_file_returns_404(self):
        self.grant_permission('view_incomingdocument')
        for file_name in ('', 'dropbox/missing.pdf'):
            with self.subTest(file_name=file_name):
                self.document.local_file = file_name
                self.document.save(update_fields=['local_file'])
                response = self.client.get(self.file_url())
                self.assertEqual(response.status_code, 404, response.get('Location'))

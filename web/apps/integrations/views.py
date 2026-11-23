import mimetypes
import re
from pathlib import PurePosixPath

from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.http import FileResponse, HttpResponseNotFound
from django.utils.http import content_disposition_header
from django.views import View

from .models import IncomingDocument


INLINE_CONTENT_TYPES = {
    'application/pdf',
    'image/bmp',
    'image/gif',
    'image/jpeg',
    'image/png',
    'image/webp',
}


class IncomingDocumentFileView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    View,
):
    permission_required = 'integrations.view_incomingdocument'
    raise_exception = True

    def get(self, request, document_id):
        document = IncomingDocument.objects.filter(pk=document_id).first()
        if document is None:
            return HttpResponseNotFound('Входящий документ не найден.')
        if not document.local_file:
            return HttpResponseNotFound(
                'Файл входящего документа не прикреплён.'
            )

        content_type, _encoding = mimetypes.guess_type(document.local_file.name)
        if content_type not in INLINE_CONTENT_TYPES:
            return HttpResponseNotFound(
                'Тип файла не поддерживает просмотр в браузере.'
            )

        try:
            file_handle = document.local_file.open('rb')
        except FileNotFoundError:
            return HttpResponseNotFound('Файл входящего документа не найден.')

        filename = PurePosixPath(
            document.local_file.name.replace('\\', '/')
        ).name
        filename = re.sub(r'[\x00-\x1f\x7f]', '-', filename).strip(' .')
        if not filename:
            filename = 'document'

        response = FileResponse(
            file_handle,
            content_type=content_type,
            as_attachment=False,
        )
        response['Content-Disposition'] = content_disposition_header(
            False,
            filename,
        )
        response['X-Content-Type-Options'] = 'nosniff'
        return response

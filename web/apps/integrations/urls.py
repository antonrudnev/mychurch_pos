from django.urls import path

from .views import IncomingDocumentFileView

app_name = 'integrations'

urlpatterns = [
    path(
        'incoming-documents/<int:document_id>/file/',
        IncomingDocumentFileView.as_view(),
        name='incoming_document_file',
    ),
]

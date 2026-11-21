from django.contrib import admin

from .models import DocumentSyncState, IncomingDocument, OcrIntegrationState


@admin.register(DocumentSyncState)
class DocumentSyncStateAdmin(admin.ModelAdmin):
    """Admin configuration for Dropbox synchronization state."""

    list_display = (
        "document_type",
        "folder_path",
        "is_active",
        "last_synced_at",
        "last_error",
    )

    def get_readonly_fields(self, request, obj=None):
        return [
            field.name
            for field in self.model._meta.fields
            if field.name not in ("id", "document_type", "folder_path", "is_active")
        ]


@admin.register(OcrIntegrationState)
class OcrIntegrationStateAdmin(admin.ModelAdmin):
    """Admin configuration for Gemini OCR integration state."""

    list_display = (
        "provider",
        "is_active",
        "last_processed_at",
        "last_error",
    )

    def get_readonly_fields(self, request, obj=None):
        return [
            field.name
            for field in self.model._meta.fields
            if field.name not in ("id", "is_active")
        ]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(IncomingDocument)
class IncomingDocumentAdmin(admin.ModelAdmin):
    """Admin configuration for downloaded Dropbox documents."""

    list_display = (
        "original_name",
        "document_type",
        "file_size",
        "status",
        "error_message",
        "created_at",
    )
    list_filter = ("status", "document_type")

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields if field.name != "id"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

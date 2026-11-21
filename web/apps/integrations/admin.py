from django.contrib import admin

from .models import DocumentSyncState, IncomingDocument


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


@admin.register(IncomingDocument)
class IncomingDocumentAdmin(admin.ModelAdmin):
    """Admin configuration for downloaded Dropbox documents."""

    list_display = (
        "original_name",
        "document_type",
        "file_size",
        "status",
        "created_at",
    )
    list_filter = ("status", "document_type")

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields if field.name != "id"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

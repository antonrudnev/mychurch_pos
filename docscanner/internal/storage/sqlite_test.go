package storage

import (
	"context"
	"database/sql"
	"path/filepath"
	"testing"
	"time"
)

func TestRepositoryQueriesAndInsertsIdempotently(t *testing.T) {
	ctx := context.Background()
	repository, err := Open(ctx, filepath.Join(t.TempDir(), "shared.sqlite3"))
	if err != nil {
		t.Fatal(err)
	}
	defer repository.Close()
	if got := repository.db.Stats().MaxOpenConnections; got != 1 {
		t.Fatalf("maximum open connections = %d, want 1", got)
	}

	_, err = repository.db.Exec(`
		CREATE TABLE document_sync_state (
			id INTEGER PRIMARY KEY,
			document_type TEXT NOT NULL,
			folder_path TEXT NOT NULL,
			is_active INTEGER NOT NULL,
			cursor TEXT,
			last_synced_at TEXT,
			last_error TEXT NOT NULL DEFAULT ''
		);
		CREATE TABLE incoming_document (
			id INTEGER PRIMARY KEY,
			document_type TEXT NOT NULL,
			dropbox_file_id TEXT NOT NULL UNIQUE,
			content_hash TEXT NOT NULL,
			original_name TEXT NOT NULL,
			dropbox_path TEXT NOT NULL,
			local_file TEXT NOT NULL,
			file_size INTEGER NOT NULL,
			status TEXT NOT NULL DEFAULT 'downloaded',
			created_at TEXT NOT NULL
		);
		INSERT INTO document_sync_state (
			id, document_type, folder_path, is_active, cursor, last_error
		) VALUES
			(1, 'product_report', '/products', 1, NULL, ''),
			(2, 'candle_report', '/candles', 0, NULL, '');
	`)
	if err != nil {
		t.Fatal(err)
	}

	states, err := repository.ActiveSyncStates(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if len(states) != 1 || states[0].ID != 1 || states[0].FolderPath != "/products" {
		t.Fatalf("active states = %#v, want only the active product folder", states)
	}

	document := IncomingDocument{
		DocumentType: "product_report",
		DropboxID:    "id:one",
		ContentHash:  "hash",
		OriginalName: "report.csv",
		DropboxPath:  "/products/report.csv",
		LocalFile:    "dropbox/product_report/report.csv",
		FileSize:     12,
		CreatedAt:    time.Date(2026, 11, 20, 20, 0, 0, 0, time.UTC),
	}
	inserted, err := repository.InsertIncomingDocument(ctx, document)
	if err != nil {
		t.Fatal(err)
	}
	if !inserted {
		t.Fatal("first insert was ignored")
	}
	inserted, err = repository.InsertIncomingDocument(ctx, document)
	if err != nil {
		t.Fatal(err)
	}
	if inserted {
		t.Fatal("duplicate insert was not ignored")
	}

	if err := repository.UpdateSyncSuccess(ctx, 1, "next-cursor", document.CreatedAt); err != nil {
		t.Fatal(err)
	}
	var cursor, lastSyncedAt, lastError string
	if err := repository.db.QueryRow(`
		SELECT cursor, last_synced_at, last_error
		FROM document_sync_state WHERE id = 1
	`).Scan(&cursor, &lastSyncedAt, &lastError); err != nil {
		t.Fatal(err)
	}
	if cursor != "next-cursor" || lastError != "" {
		t.Fatalf("successful sync state = (%q, %q)", cursor, lastError)
	}
	parsedTime, err := time.Parse(time.RFC3339Nano, lastSyncedAt)
	if err != nil || !parsedTime.Equal(document.CreatedAt) {
		t.Fatalf("last_synced_at = %q, error = %v", lastSyncedAt, err)
	}

	syncErr := sql.ErrNoRows
	if err := repository.UpdateSyncError(ctx, 1, syncErr); err != nil {
		t.Fatal(err)
	}
	if err := repository.db.QueryRow(
		"SELECT cursor, last_error FROM document_sync_state WHERE id = 1",
	).Scan(&cursor, &lastError); err != nil {
		t.Fatal(err)
	}
	if cursor != "next-cursor" || lastError != syncErr.Error() {
		t.Fatalf("failed sync state = (%q, %q)", cursor, lastError)
	}
}

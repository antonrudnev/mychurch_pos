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

	testOCR := func(t *testing.T) {
		ctx := context.Background()
		repository, err := Open(ctx, filepath.Join(t.TempDir(), "ocr.sqlite3"))
		if err != nil {
			t.Fatal(err)
		}
		defer repository.Close()

		_, err = repository.db.Exec(`
			CREATE TABLE integrations_incomingdocument (
				id INTEGER PRIMARY KEY,
				document_type TEXT NOT NULL,
				local_file TEXT NOT NULL,
				status TEXT NOT NULL,
				error_message TEXT NOT NULL DEFAULT '',
				created_at TEXT NOT NULL
			);
			CREATE TABLE integrations_ocrintegrationstate (
				id INTEGER PRIMARY KEY,
				provider TEXT NOT NULL UNIQUE,
				is_active INTEGER NOT NULL,
				last_processed_at TEXT,
				last_error TEXT NOT NULL DEFAULT ''
			);
			CREATE TABLE transactions_incomingtransaction (
				id INTEGER PRIMARY KEY,
				document_id INTEGER NOT NULL,
				report_date DATE,
				row_number INTEGER NOT NULL,
				item_id INTEGER,
				price NUMERIC NOT NULL,
				quantity INTEGER NOT NULL,
				raw_name TEXT NOT NULL,
				raw_counts TEXT NOT NULL,
				transaction_id INTEGER,
				processed_by_id INTEGER,
				is_deleted INTEGER NOT NULL,
				created_at TEXT NOT NULL
			);
			INSERT INTO integrations_incomingdocument
				(id, document_type, local_file, status, created_at)
			VALUES
				(1, 'product_report', 'dropbox/report.pdf', 'downloaded', '2026-10-30'),
				(2, 'candle_report', 'dropbox/candles.pdf', 'downloaded', '2026-10-31'),
				(3, 'product_report', 'dropbox/interrupted.pdf', 'processing', '2026-11-01');
		`)
		if err != nil {
			t.Fatal(err)
		}
		if err := repository.InitializeOCRState(ctx); err != nil {
			t.Fatal(err)
		}
		var active int
		var staleStatus string
		if err := repository.db.QueryRow(`
			SELECT is_active FROM integrations_ocrintegrationstate WHERE provider = 'gemini'
		`).Scan(&active); err != nil {
			t.Fatal(err)
		}
		if active != 1 {
			t.Fatalf("new OCR integration active = %d, want 1", active)
		}
		if err := repository.db.QueryRow(
			"SELECT status FROM integrations_incomingdocument WHERE id = 3",
		).Scan(&staleStatus); err != nil {
			t.Fatal(err)
		}
		if staleStatus != "downloaded" {
			t.Fatalf("recovered document status = %q, want downloaded", staleStatus)
		}
		if err := repository.SetMissingGeminiKeyError(ctx); err != nil {
			t.Fatal(err)
		}
		if err := repository.ClearMissingGeminiKeyError(ctx); err != nil {
			t.Fatal(err)
		}
		var lastError string
		if err := repository.db.QueryRow(`
			SELECT last_error FROM integrations_ocrintegrationstate WHERE provider = 'gemini'
		`).Scan(&lastError); err != nil {
			t.Fatal(err)
		}
		if lastError != "" {
			t.Fatalf("missing key error after clearing = %q, want empty", lastError)
		}
		if _, err := repository.db.Exec(`
			UPDATE integrations_ocrintegrationstate SET is_active = 0 WHERE provider = 'gemini'
		`); err != nil {
			t.Fatal(err)
		}
		isActive, err := repository.OCRIntegrationActive(ctx)
		if err != nil {
			t.Fatal(err)
		}
		if isActive {
			t.Fatal("OCR integration should be inactive")
		}
		if _, err := repository.db.Exec(`
			UPDATE integrations_ocrintegrationstate SET is_active = 1, last_error = 'old error'
			WHERE provider = 'gemini'
		`); err != nil {
			t.Fatal(err)
		}

		document, err := repository.ClaimNextOCRDocument(ctx)
		if err != nil {
			t.Fatal(err)
		}
		if document == nil || document.ID != 1 || document.DocumentType != "product_report" {
			t.Fatalf("claimed document = %#v", document)
		}
		itemID := int64(7)
		err = repository.SaveOCRTransactions(ctx, document.ID, []IncomingTransaction{
			{
				ReportDate: "2026-10-30",
				ItemID:     &itemID,
				Price:      40,
				Quantity:   5,
				RawName:    "0123",
				RawCounts:  []byte(`[[1,1,1,2],40]`),
			},
			{
				Price:     20,
				Quantity:  1,
				RawName:   "",
				RawCounts: []byte(`[1]`),
			},
		})
		if err != nil {
			t.Fatal(err)
		}
		var lastProcessedAt sql.NullString
		if err := repository.db.QueryRow(`
			SELECT last_processed_at, last_error
			FROM integrations_ocrintegrationstate WHERE provider = 'gemini'
		`).Scan(&lastProcessedAt, &lastError); err != nil {
			t.Fatal(err)
		}
		if !lastProcessedAt.Valid || lastError != "" {
			t.Fatalf("successful OCR state = (%v, %q)", lastProcessedAt, lastError)
		}

		var status string
		if err := repository.db.QueryRow(
			"SELECT status, error_message FROM integrations_incomingdocument WHERE id = 1",
		).Scan(&status, &lastError); err != nil {
			t.Fatal(err)
		}
		if status != "processed" || lastError != "" {
			t.Fatalf("document status/error = %q/%q, want processed/empty", status, lastError)
		}
		rows, err := repository.db.Query(`
			SELECT row_number, item_id, CAST(report_date AS TEXT), raw_name, raw_counts, transaction_id,
				processed_by_id, is_deleted, created_at
			FROM transactions_incomingtransaction
			WHERE document_id = 1
			ORDER BY row_number
		`)
		if err != nil {
			t.Fatal(err)
		}
		defer rows.Close()
		var count int
		for rows.Next() {
			var rowNumber, isDeleted int
			var rowItemID, transactionID, processedByID sql.NullInt64
			var reportDate, rawName, rawCounts, createdAt sql.NullString
			if err := rows.Scan(
				&rowNumber, &rowItemID, &reportDate, &rawName, &rawCounts, &transactionID,
				&processedByID, &isDeleted, &createdAt,
			); err != nil {
				t.Fatal(err)
			}
			count++
			if rowNumber != count || !createdAt.Valid || isDeleted != 0 ||
				transactionID.Valid || processedByID.Valid {
				t.Fatalf("persisted row metadata is invalid: row=%d created=%v", rowNumber, createdAt)
			}
			if count == 1 && (!rowItemID.Valid || rowItemID.Int64 != itemID ||
				reportDate.String != "2026-10-30" || rawCounts.String != `[[1,1,1,2],40]`) {
				t.Fatalf("first persisted row is invalid: item=%v date=%v raw_counts=%v",
					rowItemID, reportDate, rawCounts)
			}
			if count == 2 && (!rawName.Valid || rawName.String != "" || rowItemID.Valid || reportDate.Valid) {
				t.Fatalf("nullable fields/empty raw_name are invalid: raw_name=%v item=%v date=%v",
					rawName, rowItemID, reportDate)
			}
		}
		if err := rows.Err(); err != nil {
			t.Fatal(err)
		}
		if count != 2 {
			t.Fatalf("persisted row count = %d, want 2", count)
		}

		next, err := repository.ClaimNextOCRDocument(ctx)
		if err != nil {
			t.Fatal(err)
		}
		if next == nil || next.ID != 2 {
			t.Fatalf("next claimed document = %#v, want ID 2", next)
		}
		if err := repository.SetOCRIntegrationError(ctx, "quota exceeded"); err != nil {
			t.Fatal(err)
		}
		if err := repository.RetryOCRDocument(ctx, 2); err != nil {
			t.Fatal(err)
		}
		if err := repository.db.QueryRow(
			"SELECT status, error_message FROM integrations_incomingdocument WHERE id = 2",
		).Scan(&status, &lastError); err != nil {
			t.Fatal(err)
		}
		if status != "downloaded" || lastError != "" {
			t.Fatalf("retryable document status/error = %q/%q", status, lastError)
		}
		next, err = repository.ClaimNextOCRDocument(ctx)
		if err != nil {
			t.Fatal(err)
		}
		if next == nil || next.ID != 2 {
			t.Fatalf("reclaimed document = %#v, want ID 2", next)
		}
		_, err = repository.db.Exec(`
			CREATE TRIGGER reject_second_ocr_row
			BEFORE INSERT ON transactions_incomingtransaction
			WHEN NEW.row_number = 2
			BEGIN
				SELECT RAISE(ABORT, 'test insert failure');
			END;
			UPDATE integrations_incomingdocument SET status = 'processing' WHERE id = 2;
		`)
		if err != nil {
			t.Fatal(err)
		}
		if err := repository.SaveOCRTransactions(ctx, 2, []IncomingTransaction{
			{Price: 1, Quantity: 1, RawCounts: []byte(`[1]`)},
			{Price: 1, Quantity: 1, RawCounts: []byte(`[1]`)},
		}); err == nil {
			t.Fatal("expected second-row insert to fail")
		}
		var persistedCount int
		if err := repository.db.QueryRow(
			"SELECT COUNT(*) FROM transactions_incomingtransaction WHERE document_id = 2",
		).Scan(&persistedCount); err != nil {
			t.Fatal(err)
		}
		if persistedCount != 0 {
			t.Fatalf("rows persisted after failed transaction = %d, want 0", persistedCount)
		}
		if err := repository.MarkOCRDocumentError(ctx, 2, "invalid response"); err != nil {
			t.Fatal(err)
		}
		if err := repository.db.QueryRow(
			"SELECT status, error_message FROM integrations_incomingdocument WHERE id = 2",
		).Scan(&status, &lastError); err != nil {
			t.Fatal(err)
		}
		if status != "error" || lastError != "invalid response" {
			t.Fatalf("failed document status/error = %q/%q", status, lastError)
		}
	}
	defer repository.Close()
	if got := repository.db.Stats().MaxOpenConnections; got != 1 {
		t.Fatalf("maximum open connections = %d, want 1", got)
	}

	_, err = repository.db.Exec(`
		CREATE TABLE integrations_documentsyncstate (
			id INTEGER PRIMARY KEY,
			document_type TEXT NOT NULL,
			folder_path TEXT NOT NULL,
			is_active INTEGER NOT NULL,
			cursor TEXT,
			last_synced_at TEXT,
			last_error TEXT NOT NULL DEFAULT ''
		);
		CREATE TABLE integrations_incomingdocument (
			id INTEGER PRIMARY KEY,
			document_type TEXT NOT NULL,
			dropbox_file_id TEXT NOT NULL UNIQUE,
			content_hash TEXT NOT NULL,
			original_name TEXT NOT NULL,
			dropbox_path TEXT NOT NULL,
			local_file TEXT NOT NULL,
			file_size INTEGER NOT NULL,
			status TEXT NOT NULL DEFAULT 'downloaded',
			error_message TEXT NOT NULL DEFAULT '',
			created_at TEXT NOT NULL
		);
		INSERT INTO integrations_documentsyncstate (
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
		FROM integrations_documentsyncstate WHERE id = 1
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
		"SELECT cursor, last_error FROM integrations_documentsyncstate WHERE id = 1",
	).Scan(&cursor, &lastError); err != nil {
		t.Fatal(err)
	}
	if cursor != "next-cursor" || lastError != syncErr.Error() {
		t.Fatalf("failed sync state = (%q, %q)", cursor, lastError)
	}
	t.Run("OCRDocumentClaimAndSaveArePersisted", testOCR)
}

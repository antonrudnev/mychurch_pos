package storage

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"runtime"
	"time"

	_ "modernc.org/sqlite"
)

type Repository struct {
	db *sql.DB
}

const (
	ocrProvider      = "gemini"
	missingGeminiKey = "GEMINI_API_KEY не задан в переменных окружения"
)

type SyncState struct {
	ID           int64
	DocumentType string
	FolderPath   string
	Cursor       sql.NullString
}

type IncomingDocument struct {
	DocumentType string
	DropboxID    string
	ContentHash  string
	OriginalName string
	DropboxPath  string
	LocalFile    string
	FileSize     int64
	CreatedAt    time.Time
}

type OCRDocument struct {
	ID           int64
	DocumentType string
	LocalFile    string
}

type CatalogItem struct {
	ID       int64
	ItemType string
	Name     string
	Handle   string
	Price    float64
}

type IncomingTransaction struct {
	ReportDate string
	ItemID     *int64
	Price      float64
	Quantity   int64
	RawName    string
	RawCounts  []byte
}

func Open(ctx context.Context, dbPath string) (*Repository, error) {
	if dbPath == "" {
		return nil, errors.New("database path is empty")
	}
	if err := os.MkdirAll(filepath.Dir(dbPath), 0o755); err != nil {
		return nil, fmt.Errorf("create database directory: %w", err)
	}

	db, err := sql.Open("sqlite", buildDSN(dbPath))
	if err != nil {
		return nil, fmt.Errorf("open SQLite database: %w", err)
	}
	db.SetMaxOpenConns(1)
	db.SetMaxIdleConns(1)

	if err := db.PingContext(ctx); err != nil {
		_ = db.Close()
		return nil, fmt.Errorf("connect to SQLite database: %w", err)
	}
	return &Repository{db: db}, nil
}

func (r *Repository) Close() error {
	return r.db.Close()
}

func (r *Repository) ActiveSyncStates(ctx context.Context) ([]SyncState, error) {
	rows, err := r.db.QueryContext(ctx, `
		SELECT id, document_type, folder_path, cursor
		FROM integrations_documentsyncstate
		WHERE is_active = 1
		ORDER BY id
	`)
	if err != nil {
		return nil, fmt.Errorf("query active Dropbox folders: %w", err)
	}
	defer rows.Close()

	var states []SyncState
	for rows.Next() {
		var state SyncState
		if err := rows.Scan(
			&state.ID,
			&state.DocumentType,
			&state.FolderPath,
			&state.Cursor,
		); err != nil {
			return nil, fmt.Errorf("read Dropbox folder state: %w", err)
		}
		states = append(states, state)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate Dropbox folder states: %w", err)
	}
	return states, nil
}

func (r *Repository) UpdateSyncSuccess(
	ctx context.Context,
	id int64,
	cursor string,
	syncedAt time.Time,
) error {
	_, err := r.db.ExecContext(ctx, `
		UPDATE integrations_documentsyncstate
		SET cursor = ?, last_synced_at = ?, last_error = ''
		WHERE id = ?
	`, cursor, syncedAt.UTC().Format(time.RFC3339Nano), id)
	if err != nil {
		return fmt.Errorf("update successful sync state %d: %w", id, err)
	}
	return nil
}

func (r *Repository) UpdateSyncError(ctx context.Context, id int64, syncErr error) error {
	_, err := r.db.ExecContext(ctx, `
		UPDATE integrations_documentsyncstate
		SET last_error = ?
		WHERE id = ?
	`, syncErr.Error(), id)
	if err != nil {
		return fmt.Errorf("update failed sync state %d: %w", id, err)
	}
	return nil
}

func (r *Repository) InsertIncomingDocument(
	ctx context.Context,
	document IncomingDocument,
) (bool, error) {
	if document.FileSize < 0 {
		return false, fmt.Errorf("invalid file size %d", document.FileSize)
	}
	result, err := r.db.ExecContext(ctx, `
		INSERT OR IGNORE INTO integrations_incomingdocument (
			document_type,
			dropbox_file_id,
			content_hash,
			original_name,
			dropbox_path,
			local_file,
			file_size,
			status,
			error_message,
			created_at
		) VALUES (?, ?, ?, ?, ?, ?, ?, 'downloaded', '', ?)
	`,
		document.DocumentType,
		document.DropboxID,
		document.ContentHash,
		document.OriginalName,
		document.DropboxPath,
		document.LocalFile,
		document.FileSize,
		document.CreatedAt.UTC().Format(time.RFC3339Nano),
	)
	if err != nil {
		return false, fmt.Errorf("insert incoming document %q: %w", document.DropboxID, err)
	}
	inserted, err := result.RowsAffected()
	if err != nil {
		return false, fmt.Errorf("check incoming document insert result: %w", err)
	}
	return inserted > 0, nil
}

func (r *Repository) InitializeOCRState(ctx context.Context) error {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return fmt.Errorf("begin OCR state initialization: %w", err)
	}
	defer tx.Rollback()

	if _, err := tx.ExecContext(ctx, `
		INSERT OR IGNORE INTO integrations_ocrintegrationstate (
			provider, is_active, last_processed_at, last_error
		) VALUES (?, 1, NULL, '')
	`, ocrProvider); err != nil {
		return fmt.Errorf("ensure Gemini OCR integration state: %w", err)
	}
	if _, err := tx.ExecContext(ctx, `
		UPDATE integrations_incomingdocument
		SET status = 'downloaded'
		WHERE status = 'processing'
	`); err != nil {
		return fmt.Errorf("reset interrupted OCR documents: %w", err)
	}
	if err := tx.Commit(); err != nil {
		return fmt.Errorf("commit OCR state initialization: %w", err)
	}
	return nil
}

func (r *Repository) OCRIntegrationActive(ctx context.Context) (bool, error) {
	var active int
	if err := r.db.QueryRowContext(ctx, `
		SELECT is_active
		FROM integrations_ocrintegrationstate
		WHERE provider = ?
	`, ocrProvider).Scan(&active); err != nil {
		return false, fmt.Errorf("read Gemini OCR integration status: %w", err)
	}
	return active == 1, nil
}

func (r *Repository) SetOCRIntegrationError(ctx context.Context, message string) error {
	if _, err := r.db.ExecContext(ctx, `
		UPDATE integrations_ocrintegrationstate
		SET last_error = ?
		WHERE provider = ?
	`, message, ocrProvider); err != nil {
		return fmt.Errorf("save Gemini OCR integration error: %w", err)
	}
	return nil
}

func (r *Repository) SetMissingGeminiKeyError(ctx context.Context) error {
	return r.SetOCRIntegrationError(ctx, missingGeminiKey)
}

func (r *Repository) ClearMissingGeminiKeyError(ctx context.Context) error {
	if _, err := r.db.ExecContext(ctx, `
		UPDATE integrations_ocrintegrationstate
		SET last_error = ''
		WHERE provider = ? AND last_error = ?
	`, ocrProvider, missingGeminiKey); err != nil {
		return fmt.Errorf("clear missing Gemini API key error: %w", err)
	}
	return nil
}

func (r *Repository) ClearOCRIntegrationError(ctx context.Context) error {
	if _, err := r.db.ExecContext(ctx, `
		UPDATE integrations_ocrintegrationstate
		SET last_error = ''
		WHERE provider = ?
	`, ocrProvider); err != nil {
		return fmt.Errorf("clear Gemini OCR integration error: %w", err)
	}
	return nil
}

func (r *Repository) ActiveCatalog(ctx context.Context) ([]CatalogItem, error) {
	rows, err := r.db.QueryContext(ctx, `
		SELECT i.id, LOWER(it.handle) AS item_type, i.name, i.handle,
			COALESCE(CAST(i.price AS REAL), 0) AS price
		FROM directory_item i
		INNER JOIN directory_itemtype it ON i.item_type_id = it.id
		WHERE i.is_active = 1 AND (LOWER(it.handle) = 'candle' OR it.is_product_group = 1)
		ORDER BY i.order_number ASC, i.name ASC
	`)
	if err != nil {
		return nil, fmt.Errorf("query active OCR catalog: %w", err)
	}
	defer rows.Close()

	var catalog []CatalogItem
	for rows.Next() {
		var item CatalogItem
		if err := rows.Scan(&item.ID, &item.ItemType, &item.Name, &item.Handle, &item.Price); err != nil {
			return nil, fmt.Errorf("read active OCR catalog item: %w", err)
		}
		catalog = append(catalog, item)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate active OCR catalog: %w", err)
	}
	return catalog, nil
}

func (r *Repository) ClaimNextOCRDocument(ctx context.Context) (*OCRDocument, error) {
	var document OCRDocument
	err := r.db.QueryRowContext(ctx, `
		UPDATE integrations_incomingdocument
		SET status = 'processing'
		WHERE id = (
			SELECT id
			FROM integrations_incomingdocument
			WHERE status = 'downloaded'
			ORDER BY created_at ASC
			LIMIT 1
		)
		RETURNING id, document_type, local_file
	`).Scan(&document.ID, &document.DocumentType, &document.LocalFile)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("claim next downloaded document: %w", err)
	}
	return &document, nil
}

func (r *Repository) RetryOCRDocument(ctx context.Context, documentID int64) error {
	if _, err := r.db.ExecContext(ctx, `
		UPDATE integrations_incomingdocument
		SET status = 'downloaded', error_message = ''
		WHERE id = ?
	`, documentID); err != nil {
		return fmt.Errorf("return OCR document %d to queue: %w", documentID, err)
	}
	return nil
}

func (r *Repository) MarkOCRDocumentError(
	ctx context.Context,
	documentID int64,
	message string,
) error {
	if _, err := r.db.ExecContext(ctx, `
		UPDATE integrations_incomingdocument
		SET status = 'error', error_message = ?
		WHERE id = ?
	`, message, documentID); err != nil {
		return fmt.Errorf("mark OCR document %d as error: %w", documentID, err)
	}
	return nil
}

func (r *Repository) SaveOCRTransactions(
	ctx context.Context,
	documentID int64,
	transactions []IncomingTransaction,
) error {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return fmt.Errorf("begin OCR transaction for document %d: %w", documentID, err)
	}
	defer tx.Rollback()

	const insertSQL = `
		INSERT INTO transactions_incomingtransaction (
			document_id, report_date, row_number, item_id, price, quantity,
			raw_name, raw_counts, transaction_id, processed_by_id, is_deleted, created_at
		) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, 0, ?)
	`
	for index, row := range transactions {
		var reportDate any
		if row.ReportDate != "" {
			reportDate = row.ReportDate
		}
		var itemID any
		if row.ItemID != nil {
			itemID = *row.ItemID
		}
		if _, err := tx.ExecContext(
			ctx,
			insertSQL,
			documentID,
			reportDate,
			index+1,
			itemID,
			row.Price,
			row.Quantity,
			row.RawName,
			string(row.RawCounts),
			time.Now().UTC().Format("2006-01-02 15:04:05.000000"),
		); err != nil {
			return fmt.Errorf("insert OCR row %d for document %d: %w", index+1, documentID, err)
		}
	}
	if _, err := tx.ExecContext(ctx, `
		UPDATE integrations_incomingdocument
		SET status = 'processed', error_message = ''
		WHERE id = ?
	`, documentID); err != nil {
		return fmt.Errorf("mark OCR document %d as processed: %w", documentID, err)
	}
	if _, err := tx.ExecContext(ctx, `
		UPDATE integrations_ocrintegrationstate
		SET last_processed_at = ?, last_error = ''
		WHERE provider = ?
	`, time.Now().UTC().Format("2006-01-02 15:04:05.000000"), ocrProvider); err != nil {
		return fmt.Errorf("update Gemini OCR integration success: %w", err)
	}
	if err := tx.Commit(); err != nil {
		return fmt.Errorf("commit OCR transaction for document %d: %w", documentID, err)
	}
	return nil
}

func buildDSN(dbPath string) string {
	absolutePath, err := filepath.Abs(dbPath)
	if err != nil {
		absolutePath = filepath.Clean(dbPath)
	}
	path := filepath.ToSlash(absolutePath)
	if runtime.GOOS == "windows" {
		path = "/" + path
	}

	u := url.URL{Scheme: "file", Path: path}
	query := u.Query()
	query.Add("_pragma", "busy_timeout(5000)")
	query.Add("_pragma", "journal_mode(WAL)")
	u.RawQuery = query.Encode()
	return u.String()
}

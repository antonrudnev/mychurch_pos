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
		FROM transactions_document_sync_state
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
		UPDATE transactions_document_sync_state
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
		UPDATE transactions_document_sync_state
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
		INSERT OR IGNORE INTO transactions_incoming_document (
			document_type,
			dropbox_file_id,
			content_hash,
			original_name,
			dropbox_path,
			local_file,
			file_size,
			status,
			created_at
		) VALUES (?, ?, ?, ?, ?, ?, ?, 'downloaded', ?)
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
		return false, fmt.Errorf("insert transactions_incoming document %q: %w", document.DropboxID, err)
	}
	inserted, err := result.RowsAffected()
	if err != nil {
		return false, fmt.Errorf("check incoming document insert result: %w", err)
	}
	return inserted > 0, nil
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

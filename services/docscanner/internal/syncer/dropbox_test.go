package syncer

import (
	"context"
	"database/sql"
	"errors"
	"io"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"docscanner/internal/config"
	"docscanner/internal/storage"
	"github.com/dropbox/dropbox-sdk-go-unofficial/v6/dropbox/files"
	"golang.org/x/text/unicode/norm"
)

type testFilesClient struct {
	downloadArg *files.DownloadArg
	content     string
	downloadErr error
}

func (c *testFilesClient) ListFolderContext(
	context.Context,
	*files.ListFolderArg,
) (*files.ListFolderResult, error) {
	return nil, errors.New("unexpected ListFolderContext call")
}

func (c *testFilesClient) ListFolderContinueContext(
	context.Context,
	*files.ListFolderContinueArg,
) (*files.ListFolderResult, error) {
	return nil, errors.New("unexpected ListFolderContinueContext call")
}

func (c *testFilesClient) DownloadContext(
	_ context.Context,
	arg *files.DownloadArg,
) (*files.FileMetadata, io.ReadCloser, error) {
	c.downloadArg = arg
	if c.downloadErr != nil {
		return nil, nil, c.downloadErr
	}
	return nil, io.NopCloser(strings.NewReader(c.content)), nil
}

func TestDownloadUsesASCIIFileIDAndSafeDiskName(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	dbPath := filepath.Join(root, "db.sqlite3")
	database, err := sql.Open("sqlite", dbPath)
	if err != nil {
		t.Fatal(err)
	}
	_, err = database.Exec(`
		CREATE TABLE integrations_incomingdocument (
			id INTEGER PRIMARY KEY,
			document_type TEXT NOT NULL,
			dropbox_file_id TEXT NOT NULL UNIQUE,
			content_hash TEXT NOT NULL,
			original_name TEXT NOT NULL,
			dropbox_path TEXT NOT NULL,
			local_file TEXT NOT NULL,
			file_size INTEGER NOT NULL,
			status TEXT NOT NULL,
			error_message TEXT NOT NULL DEFAULT '',
			created_at TEXT NOT NULL
		);
	`)
	if err != nil {
		t.Fatal(err)
	}
	if err := database.Close(); err != nil {
		t.Fatal(err)
	}
	repository, err := storage.Open(ctx, dbPath)
	if err != nil {
		t.Fatal(err)
	}
	defer repository.Close()

	const fileID = "id:0123456789abcdef"
	const originalName = "Свечная ведомость.pdf"
	content := "PDF contents"
	client := &testFilesClient{content: content}
	syncer := New(repository, config.Config{DownloadDir: root}, slog.New(slog.NewTextHandler(io.Discard, nil)))
	file := &files.FileMetadata{
		Metadata: files.Metadata{
			Name:        originalName,
			PathLower:   "/home/ведомости/свечная/" + norm.NFD.String(originalName),
			PathDisplay: "/Home/Ведомости/Свечная/" + originalName,
		},
		Id:   fileID,
		Size: uint64(len(content)),
	}

	if err := syncer.downloadFile(ctx, client, candleReport, file); err != nil {
		t.Fatal(err)
	}
	if client.downloadArg == nil || client.downloadArg.Path != fileID {
		t.Fatalf("Dropbox download path = %#v, want ASCII file ID %q", client.downloadArg, fileID)
	}
	if strings.ContainsAny(client.downloadArg.Path, "ВедомостиСвечная") {
		t.Fatalf("Dropbox API path contains non-ASCII characters: %q", client.downloadArg.Path)
	}

	localName := safeLocalFilename(fileID, originalName)
	if strings.ContainsAny(localName, "Свечнаяведомость") || !strings.HasSuffix(localName, ".pdf") {
		t.Fatalf("unsafe local filename = %q", localName)
	}
	if _, err := os.Stat(filepath.Join(root, candleReport, localName)); err != nil {
		t.Fatalf("downloaded file not found under safe local name: %v", err)
	}

	var storedName, storedPath, storedDropboxPath string
	database, err = sql.Open("sqlite", dbPath)
	if err != nil {
		t.Fatal(err)
	}
	defer database.Close()
	if err := database.QueryRow(`
		SELECT original_name, local_file, dropbox_path
		FROM integrations_incomingdocument WHERE dropbox_file_id = ?
	`, fileID).Scan(&storedName, &storedPath, &storedDropboxPath); err != nil {
		t.Fatal(err)
	}
	if storedName != originalName {
		t.Fatalf("stored original name = %q, want %q", storedName, originalName)
	}
	if storedPath != filepath.ToSlash(filepath.Join("dropbox", candleReport, localName)) {
		t.Fatalf("stored local file = %q", storedPath)
	}
	if storedDropboxPath != file.PathDisplay {
		t.Fatalf("stored Dropbox display path = %q, want %q", storedDropboxPath, file.PathDisplay)
	}
}

func TestDropboxPathNormalizationMatchesNFCAndNFD(t *testing.T) {
	folderNFC := "/Home/Ведомости/Свечная"
	folderNFD := norm.NFD.String(folderNFC)
	entryNFD := norm.NFD.String(folderNFC + "/отчет.pdf")

	if normalizedDropboxPath(folderNFC) != normalizedDropboxPath(folderNFD) {
		t.Fatal("NFC and NFD folder paths normalized differently")
	}
	if !isDropboxPathWithin(folderNFC, entryNFD) {
		t.Fatal("NFD file path was not recognized inside NFC folder")
	}
	if isDropboxPathWithin(folderNFC, "/Home/Ведомости/Свечная-Архив/file.pdf") {
		t.Fatal("sibling path was incorrectly treated as a child")
	}
}

func TestSyncFolderPersistsAndReturnsErrors(t *testing.T) {
	ctx := context.Background()
	dbPath := filepath.Join(t.TempDir(), "sync-state.sqlite3")
	database, err := sql.Open("sqlite", dbPath)
	if err != nil {
		t.Fatal(err)
	}
	_, err = database.Exec(`
		CREATE TABLE integrations_documentsyncstate (
			id INTEGER PRIMARY KEY,
			last_error TEXT NOT NULL DEFAULT ''
		);
		INSERT INTO integrations_documentsyncstate (id) VALUES (1);
	`)
	if err != nil {
		t.Fatal(err)
	}
	if err := database.Close(); err != nil {
		t.Fatal(err)
	}
	repository, err := storage.Open(ctx, dbPath)
	if err != nil {
		t.Fatal(err)
	}
	defer repository.Close()

	syncer := New(repository, config.Config{}, slog.New(slog.NewTextHandler(io.Discard, nil)))
	state := storage.SyncState{
		ID:           1,
		DocumentType: productReport,
		FolderPath:   "/Home/Ведомости/Товарная",
	}
	if err := syncer.syncFolder(ctx, state); err == nil {
		t.Fatal("expected folder synchronization error")
	}

	database, err = sql.Open("sqlite", dbPath)
	if err != nil {
		t.Fatal(err)
	}
	defer database.Close()
	var lastError string
	if err := database.QueryRow(
		"SELECT last_error FROM integrations_documentsyncstate WHERE id = 1",
	).Scan(&lastError); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(lastError, "DROPBOX_APP_KEY") {
		t.Fatalf("stored sync error = %q", lastError)
	}
}

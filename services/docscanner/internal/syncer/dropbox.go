package syncer

import (
	"context"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/dropbox/dropbox-sdk-go-unofficial/v6/dropbox"
	"github.com/dropbox/dropbox-sdk-go-unofficial/v6/dropbox/files"
	dropboxoauth "github.com/dropbox/dropbox-sdk-go-unofficial/v6/dropbox/oauth"
	"golang.org/x/oauth2"

	"docscanner/internal/config"
	"docscanner/internal/storage"
)

const (
	productReport = "product_report"
	candleReport  = "candle_report"
)

type contextFilesClient interface {
	ListFolderContext(context.Context, *files.ListFolderArg) (*files.ListFolderResult, error)
	ListFolderContinueContext(context.Context, *files.ListFolderContinueArg) (*files.ListFolderResult, error)
	DownloadContext(context.Context, *files.DownloadArg) (*files.FileMetadata, io.ReadCloser, error)
}

type Syncer struct {
	repository *storage.Repository
	config     config.Config
	logger     *slog.Logger

	tokenMu      sync.Mutex
	tokenSources map[string]*dropboxoauth.CachedTokenSource
}

func New(repository *storage.Repository, cfg config.Config, logger *slog.Logger) *Syncer {
	return &Syncer{
		repository:   repository,
		config:       cfg,
		logger:       logger,
		tokenSources: make(map[string]*dropboxoauth.CachedTokenSource),
	}
}

func (s *Syncer) SyncAll(ctx context.Context) error {
	states, err := s.repository.ActiveSyncStates(ctx)
	if err != nil {
		return fmt.Errorf("load active Dropbox folders: %w", err)
	}
	if len(states) == 0 {
		s.logger.Info("No active Dropbox folders to synchronize")
		return nil
	}

	var wg sync.WaitGroup
	for _, state := range states {
		state := state
		wg.Add(1)
		go func() {
			defer wg.Done()
			s.syncFolder(ctx, state)
		}()
	}
	wg.Wait()
	return nil
}

func (s *Syncer) syncFolder(ctx context.Context, state storage.SyncState) {
	cursor := ""
	if state.Cursor.Valid {
		cursor = state.Cursor.String
	}

	newCursor, err := s.syncFolderContents(ctx, state, cursor)
	if err != nil {
		if updateErr := s.repository.UpdateSyncError(ctx, state.ID, err); updateErr != nil {
			s.logger.Error(
				"Dropbox folder sync failed and its error could not be saved",
				"folder_id", state.ID,
				"folder_path", state.FolderPath,
				"error", err,
				"state_update_error", updateErr,
			)
			return
		}
		s.logger.Error(
			"Dropbox folder sync failed",
			"folder_id", state.ID,
			"folder_path", state.FolderPath,
			"error", err,
		)
		return
	}

	if err := s.repository.UpdateSyncSuccess(ctx, state.ID, newCursor, time.Now().UTC()); err != nil {
		s.logger.Error(
			"Dropbox folder synced but its state could not be saved",
			"folder_id", state.ID,
			"folder_path", state.FolderPath,
			"error", err,
		)
		return
	}
	s.logger.Info(
		"Dropbox folder synchronized",
		"folder_id", state.ID,
		"document_type", state.DocumentType,
		"folder_path", state.FolderPath,
	)
}

func (s *Syncer) syncFolderContents(
	ctx context.Context,
	state storage.SyncState,
	cursor string,
) (string, error) {
	if state.DocumentType != productReport && state.DocumentType != candleReport {
		return "", fmt.Errorf("unsupported document type %q", state.DocumentType)
	}
	if strings.TrimSpace(state.FolderPath) == "" {
		return "", errors.New("Dropbox folder path is empty")
	}
	client, err := s.filesClient(ctx)
	if err != nil {
		return "", err
	}

	var result *files.ListFolderResult
	if cursor == "" {
		result, err = client.ListFolderContext(ctx, &files.ListFolderArg{
			Path:      state.FolderPath,
			Recursive: true,
		})
	} else {
		result, err = client.ListFolderContinueContext(
			ctx,
			&files.ListFolderContinueArg{Cursor: cursor},
		)
	}
	if err != nil {
		return "", fmt.Errorf("list Dropbox folder %q: %w", state.FolderPath, err)
	}

	for {
		for _, entry := range result.Entries {
			file, ok := entry.(*files.FileMetadata)
			if !ok {
				continue
			}
			if err := s.downloadFile(ctx, client, state.DocumentType, file); err != nil {
				return "", err
			}
		}

		if !result.HasMore {
			return result.Cursor, nil
		}
		result, err = client.ListFolderContinueContext(
			ctx,
			&files.ListFolderContinueArg{Cursor: result.Cursor},
		)
		if err != nil {
			return "", fmt.Errorf("continue listing Dropbox folder %q: %w", state.FolderPath, err)
		}
	}
}

func (s *Syncer) downloadFile(
	ctx context.Context,
	client contextFilesClient,
	documentType string,
	file *files.FileMetadata,
) error {
	if file.Id == "" {
		return errors.New("Dropbox returned a file without an ID")
	}
	if file.Name == "" || file.Name == "." || file.Name == ".." ||
		strings.ContainsAny(file.Name, `/\`) || filepath.Base(file.Name) != file.Name {
		return fmt.Errorf("Dropbox returned an unsafe filename %q", file.Name)
	}
	if file.Size > uint64(^uint64(0)>>1) {
		return fmt.Errorf("file %q is too large to store", file.Name)
	}

	remotePath := file.PathLower
	if remotePath == "" {
		remotePath = file.PathDisplay
	}
	if remotePath == "" {
		return fmt.Errorf("Dropbox returned no path for file %q", file.Name)
	}

	_, content, err := client.DownloadContext(ctx, files.NewDownloadArg(remotePath))
	if err != nil {
		return fmt.Errorf("download Dropbox file %q: %w", file.Name, err)
	}
	defer content.Close()

	targetDir := filepath.Join(s.config.DownloadDir, documentType)
	if err := os.MkdirAll(targetDir, 0o755); err != nil {
		return fmt.Errorf("create download directory for %q: %w", file.Name, err)
	}
	targetPath := filepath.Join(targetDir, file.Name)
	tempFile, err := os.CreateTemp(targetDir, ".docscanner-*.tmp")
	if err != nil {
		return fmt.Errorf("create temporary file for %q: %w", file.Name, err)
	}
	tempPath := tempFile.Name()
	defer os.Remove(tempPath)

	written, copyErr := io.Copy(tempFile, content)
	if copyErr != nil {
		_ = tempFile.Close()
		return fmt.Errorf("write downloaded file %q: %w", file.Name, copyErr)
	}
	if uint64(written) != file.Size {
		_ = tempFile.Close()
		return fmt.Errorf(
			"downloaded file %q has size %d, Dropbox reported %d",
			file.Name,
			written,
			file.Size,
		)
	}
	if err := tempFile.Sync(); err != nil {
		_ = tempFile.Close()
		return fmt.Errorf("sync downloaded file %q to disk: %w", file.Name, err)
	}
	if err := tempFile.Close(); err != nil {
		return fmt.Errorf("close downloaded file %q: %w", file.Name, err)
	}
	if err := os.Rename(tempPath, targetPath); err != nil {
		return fmt.Errorf("move downloaded file %q into place: %w", file.Name, err)
	}

	localFile := filepath.ToSlash(filepath.Join("dropbox", documentType, file.Name))
	displayPath := file.PathDisplay
	if displayPath == "" {
		displayPath = remotePath
	}
	_, err = s.repository.InsertIncomingDocument(ctx, storage.IncomingDocument{
		DocumentType: documentType,
		DropboxID:    file.Id,
		ContentHash:  file.ContentHash,
		OriginalName: file.Name,
		DropboxPath:  displayPath,
		LocalFile:    localFile,
		FileSize:     written,
		CreatedAt:    time.Now().UTC(),
	})
	if err != nil {
		return err
	}
	return nil
}

func (s *Syncer) filesClient(ctx context.Context) (contextFilesClient, error) {
	if s.config.DropboxAppKey == "" || s.config.DropboxAppSecret == "" {
		return nil, errors.New("DROPBOX_APP_KEY and DROPBOX_APP_SECRET must be configured")
	}
	if s.config.DropboxToken == "" {
		return nil, errors.New("DROPBOX_REFRESH_TOKEN must be configured")
	}

	s.tokenMu.Lock()
	tokenSource := s.tokenSources[s.config.DropboxToken]
	if tokenSource == nil {
		refreshHTTPClient := &http.Client{Timeout: 30 * time.Second}
		tokenSource = dropboxoauth.NewCachedTokenSource(
			ctx,
			s.config.DropboxAppKey,
			&oauth2.Token{RefreshToken: s.config.DropboxToken},
			dropboxoauth.WithAppSecret(s.config.DropboxAppSecret),
			dropboxoauth.WithHTTPClient(refreshHTTPClient),
		)
		s.tokenSources[s.config.DropboxToken] = tokenSource
	}
	s.tokenMu.Unlock()

	apiHTTPClient := oauth2.NewClient(ctx, tokenSource)
	apiHTTPClient.Timeout = 2 * time.Minute
	client, ok := files.New(dropbox.Config{Client: apiHTTPClient}).(contextFilesClient)
	if !ok {
		return nil, errors.New("Dropbox SDK client does not support context-aware requests")
	}
	return client, nil
}

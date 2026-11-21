package ocr

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"image"
	_ "image/gif"
	_ "image/jpeg"
	_ "image/png"
	"log/slog"
	"mime"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"docscanner/internal/parsers"
	"docscanner/internal/storage"
	"google.golang.org/genai"
)

const (
	geminiModel    = "gemini-3.5-flash-lite"
	pollInterval   = 3 * time.Second
	geminiBackoff  = 30 * time.Second
	errorSaveLimit = 5 * time.Second
)

type failureKind uint8

const (
	fileFailure failureKind = iota
	geminiFailure
	retryableFailure
)

type processingError struct {
	kind failureKind
	err  error
}

func (e *processingError) Error() string {
	return e.err.Error()
}

func (e *processingError) Unwrap() error {
	return e.err
}

func fileError(err error) error {
	return &processingError{kind: fileFailure, err: err}
}

func integrationError(err error) error {
	return &processingError{kind: geminiFailure, err: err}
}

func retryableError(err error) error {
	return &processingError{kind: retryableFailure, err: err}
}

type modelClient interface {
	GenerateContent(
		context.Context,
		string,
		[]*genai.Content,
		*genai.GenerateContentConfig,
	) (*genai.GenerateContentResponse, error)
}

type genaiModelClient struct {
	client *genai.Client
}

func (c genaiModelClient) GenerateContent(
	ctx context.Context,
	model string,
	contents []*genai.Content,
	config *genai.GenerateContentConfig,
) (*genai.GenerateContentResponse, error) {
	return c.client.Models.GenerateContent(ctx, model, contents, config)
}

type OCRWorker struct {
	repository  *storage.Repository
	model       modelClient
	downloadDir string
	registry    *parsers.Registry
	logger      *slog.Logger
}

func NewWorker(
	ctx context.Context,
	repository *storage.Repository,
	apiKey string,
	downloadDir string,
	logger *slog.Logger,
) (*OCRWorker, error) {
	if strings.TrimSpace(apiKey) == "" {
		return nil, errors.New("GEMINI_API_KEY must be configured")
	}
	client, err := genai.NewClient(ctx, &genai.ClientConfig{APIKey: apiKey})
	if err != nil {
		return nil, fmt.Errorf("create Gemini client: %w", err)
	}
	return &OCRWorker{
		repository:  repository,
		model:       genaiModelClient{client: client},
		downloadDir: downloadDir,
		registry:    parsers.NewRegistry(),
		logger:      logger,
	}, nil
}

func (w *OCRWorker) Run(ctx context.Context) {
	for {
		if ctx.Err() != nil {
			return
		}
		active, err := w.repository.OCRIntegrationActive(ctx)
		if err != nil {
			if ctx.Err() != nil {
				return
			}
			w.logger.Error("Could not read Gemini OCR integration status", "error", err)
			if !wait(ctx, pollInterval) {
				return
			}
			continue
		}
		if !active {
			if !wait(ctx, pollInterval) {
				return
			}
			continue
		}

		document, err := w.repository.ClaimNextOCRDocument(ctx)
		if err != nil {
			if ctx.Err() != nil {
				return
			}
			w.logger.Error("Could not claim incoming document for OCR", "error", err)
			if !wait(ctx, pollInterval) {
				return
			}
			continue
		}
		if document == nil {
			if !wait(ctx, pollInterval) {
				return
			}
			continue
		}
		if err := w.process(ctx, *document); err != nil {
			var processingErr *processingError
			if !errors.As(err, &processingErr) {
				processingErr = &processingError{kind: retryableFailure, err: err}
			}
			if !w.recordFailure(ctx, *document, processingErr) {
				return
			}
			if processingErr.kind == geminiFailure || processingErr.kind == retryableFailure {
				if !wait(ctx, geminiBackoff) {
					return
				}
			}
			continue
		}
		w.logger.Info(
			"Incoming document OCR completed",
			"document_id", document.ID,
			"document_type", document.DocumentType,
		)
	}
}

func (w *OCRWorker) recordFailure(
	ctx context.Context,
	document storage.OCRDocument,
	failure *processingError,
) bool {
	w.logger.Error(
		"Could not process incoming document",
		"document_id", document.ID,
		"document_type", document.DocumentType,
		"error", failure,
	)
	updateCtx, cancel := context.WithTimeout(context.Background(), errorSaveLimit)
	defer cancel()

	if ctx.Err() != nil {
		if err := w.repository.RetryOCRDocument(updateCtx, document.ID); err != nil {
			w.logger.Error("Could not requeue interrupted OCR document", "document_id", document.ID, "error", err)
		}
		return false
	}

	switch failure.kind {
	case fileFailure:
		if err := w.repository.MarkOCRDocumentError(updateCtx, document.ID, failure.Error()); err != nil {
			w.logger.Error("Could not save OCR document error", "document_id", document.ID, "error", err)
		}
		if err := w.repository.ClearOCRIntegrationError(updateCtx); err != nil {
			w.logger.Error("Could not clear Gemini OCR integration error", "error", err)
		}
	case geminiFailure:
		if err := w.repository.SetOCRIntegrationError(updateCtx, failure.Error()); err != nil {
			w.logger.Error("Could not save Gemini OCR integration error", "error", err)
		}
		if err := w.repository.RetryOCRDocument(updateCtx, document.ID); err != nil {
			w.logger.Error("Could not requeue OCR document after Gemini failure", "document_id", document.ID, "error", err)
		}
	case retryableFailure:
		if err := w.repository.RetryOCRDocument(updateCtx, document.ID); err != nil {
			w.logger.Error("Could not requeue OCR document after system failure", "document_id", document.ID, "error", err)
		}
	}
	return true
}

func (w *OCRWorker) process(ctx context.Context, document storage.OCRDocument) error {
	parser, err := w.registry.For(document.DocumentType)
	if err != nil {
		return fileError(err)
	}
	catalog, err := w.repository.ActiveCatalog(ctx)
	if err != nil {
		return retryableError(err)
	}
	filePath, err := resolveLocalFile(w.downloadDir, document.LocalFile)
	if err != nil {
		return fileError(err)
	}
	data, err := os.ReadFile(filePath)
	if err != nil {
		return fileError(fmt.Errorf("read document file %q: %w", filePath, err))
	}
	mimeType := mime.TypeByExtension(filepath.Ext(filePath))
	if mimeType == "" || mimeType == "application/octet-stream" {
		mimeType = http.DetectContentType(data)
	}
	if !strings.HasPrefix(mimeType, "image/") && mimeType != "application/pdf" {
		return fileError(fmt.Errorf("unsupported document MIME type %q", mimeType))
	}
	if mimeType == "image/jpeg" || mimeType == "image/png" || mimeType == "image/gif" {
		if _, _, err := image.DecodeConfig(bytes.NewReader(data)); err != nil {
			return fileError(fmt.Errorf("decode image file %q: %w", filePath, err))
		}
	}

	temperature := float32(0)
	response, err := w.model.GenerateContent(ctx, geminiModel, []*genai.Content{
		genai.NewContentFromParts([]*genai.Part{
			genai.NewPartFromBytes(data, mimeType),
			genai.NewPartFromText("Распознай таблицу в этом документе."),
		}, genai.RoleUser),
	}, &genai.GenerateContentConfig{
		SystemInstruction: &genai.Content{
			Parts: []*genai.Part{genai.NewPartFromText(parser.SystemInstruction(catalog))},
		},
		Temperature:      &temperature,
		ResponseMIMEType: "application/json",
		ResponseSchema:   parser.ResponseSchema(),
	})
	if err != nil {
		return integrationError(fmt.Errorf("call Gemini for document %d: %w", document.ID, err))
	}
	if response == nil || strings.TrimSpace(response.Text()) == "" {
		return fileError(errors.New("Gemini returned an empty response"))
	}
	transactions, err := parser.Parse([]byte(response.Text()), catalog)
	if err != nil {
		return fileError(fmt.Errorf("parse Gemini response for document %d: %w", document.ID, err))
	}
	if err := w.repository.SaveOCRTransactions(ctx, document.ID, transactions); err != nil {
		return retryableError(err)
	}
	return nil
}

func resolveLocalFile(downloadDir, localFile string) (string, error) {
	if filepath.IsAbs(localFile) {
		return "", errors.New("incoming document path must be relative")
	}
	cleanPath := filepath.Clean(filepath.FromSlash(localFile))
	parts := strings.Split(cleanPath, string(filepath.Separator))
	if len(parts) < 2 || parts[0] != "dropbox" {
		return "", fmt.Errorf("incoming document path %q must start with dropbox/", localFile)
	}
	path := filepath.Join(downloadDir, filepath.Join(parts[1:]...))
	relative, err := filepath.Rel(downloadDir, path)
	if err != nil {
		return "", fmt.Errorf("resolve incoming document path: %w", err)
	}
	if relative == ".." || strings.HasPrefix(relative, ".."+string(filepath.Separator)) {
		return "", fmt.Errorf("incoming document path %q escapes the download directory", localFile)
	}
	return path, nil
}

func wait(ctx context.Context, delay time.Duration) bool {
	timer := time.NewTimer(delay)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return false
	case <-timer.C:
		return true
	}
}

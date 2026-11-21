package main

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"docscanner/internal/config"
	"docscanner/internal/ocr"
	"docscanner/internal/storage"
	"docscanner/internal/syncer"
)

const (
	webhookBodyLimit = 1 << 20
	syncDebounce     = 2500 * time.Millisecond
	syncRetryDelay   = 5 * time.Second
	shutdownTimeout  = 10 * time.Second
)

func main() {
	if err := run(); err != nil {
		slog.Error("docscanner stopped with an error", "error", err)
		os.Exit(1)
	}
}

func run() error {
	logger := slog.New(slog.NewTextHandler(os.Stdout, nil))
	cfg, err := config.Load()
	if err != nil {
		return fmt.Errorf("load configuration: %w", err)
	}
	logger.Info(
		"Starting docscanner",
		"port", cfg.Port,
		"db_path", cfg.DBPath,
		"download_dir", cfg.DownloadDir,
		"docker", cfg.InDocker,
	)

	rootCtx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	repository, err := storage.Open(rootCtx, cfg.DBPath)
	if err != nil {
		return err
	}
	defer func() {
		if err := repository.Close(); err != nil {
			logger.Error("Close SQLite database", "error", err)
		}
	}()

	if err := repository.InitializeOCRState(rootCtx); err != nil {
		return fmt.Errorf("initialize OCR integration state: %w", err)
	}
	var ocrWorker *ocr.OCRWorker
	if cfg.GeminiAPIKey == "" {
		if err := repository.SetMissingGeminiKeyError(rootCtx); err != nil {
			logger.Error("Could not save missing Gemini API key state", "error", err)
		}
		logger.Warn("OCR worker is disabled because GEMINI_API_KEY is not configured")
	} else {
		if err := repository.ClearMissingGeminiKeyError(rootCtx); err != nil {
			logger.Error("Could not clear missing Gemini API key state", "error", err)
		}
		ocrWorker, err = ocr.NewWorker(rootCtx, repository, cfg.GeminiAPIKey, cfg.DownloadDir, logger)
		if err != nil {
			logger.Error("Could not initialize OCR worker", "error", err)
			if stateErr := repository.SetOCRIntegrationError(rootCtx, err.Error()); stateErr != nil {
				logger.Error("Could not save Gemini client initialization error", "error", stateErr)
			}
		}
	}
	dropboxSyncer := syncer.New(repository, cfg, logger)
	worker := startSyncWorker(rootCtx, dropboxSyncer, logger)
	worker.Trigger()

	ocrDone := make(chan struct{})
	if ocrWorker == nil {
		close(ocrDone)
	} else {
		go func() {
			defer close(ocrDone)
			ocrWorker.Run(rootCtx)
		}()
	}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, _ *http.Request) {
		_, _ = io.WriteString(w, "OK")
	})
	mux.HandleFunc("GET /webhook", handleWebhookChallenge)
	mux.Handle("POST /webhook", newWebhookHandler(cfg.DropboxAppSecret, worker.Trigger, logger))

	server := &http.Server{
		Addr:              ":" + strings.TrimPrefix(cfg.Port, ":"),
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
	}
	serverErrors := make(chan error, 1)
	go func() {
		serverErrors <- server.ListenAndServe()
	}()

	var serverErr error
	select {
	case <-rootCtx.Done():
	case err := <-serverErrors:
		if !errors.Is(err, http.ErrServerClosed) {
			serverErr = err
			stop()
		}
	}

	shutdownCtx, cancelShutdown := context.WithTimeout(context.Background(), shutdownTimeout)
	defer cancelShutdown()
	if err := server.Shutdown(shutdownCtx); err != nil {
		logger.Error("HTTP server graceful shutdown failed", "error", err)
		if closeErr := server.Close(); closeErr != nil {
			logger.Error("Force-close HTTP server", "error", closeErr)
		}
	}
	stop()

	select {
	case <-worker.Done():
	case <-shutdownCtx.Done():
		logger.Warn("Timed out waiting for sync worker to stop")
		<-worker.Done()
	}
	select {
	case <-ocrDone:
	case <-shutdownCtx.Done():
		logger.Warn("Timed out waiting for OCR worker to stop")
		<-ocrDone
	}

	if serverErr != nil {
		return fmt.Errorf("serve HTTP: %w", serverErr)
	}
	return nil
}

func handleWebhookChallenge(w http.ResponseWriter, r *http.Request) {
	challenge := r.URL.Query().Get("challenge")
	if challenge == "" {
		http.Error(w, "missing challenge", http.StatusBadRequest)
		return
	}
	w.Header().Set("Content-Type", "text/plain")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	_, _ = io.WriteString(w, challenge)
}

func newWebhookHandler(secret string, trigger func(), logger *slog.Logger) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if secret == "" {
			http.Error(w, "webhook signature validation is not configured", http.StatusServiceUnavailable)
			return
		}

		body, err := io.ReadAll(io.LimitReader(r.Body, webhookBodyLimit+1))
		if err != nil {
			http.Error(w, "could not read webhook body", http.StatusBadRequest)
			return
		}
		if len(body) > webhookBodyLimit {
			http.Error(w, "webhook body too large", http.StatusRequestEntityTooLarge)
			return
		}
		if !validDropboxSignature(secret, body, r.Header.Get("X-Dropbox-Signature")) {
			http.Error(w, "invalid webhook signature", http.StatusUnauthorized)
			return
		}

		trigger()
		w.WriteHeader(http.StatusOK)
		if _, err := io.WriteString(w, "OK"); err != nil {
			logger.Warn("Could not write webhook acknowledgement", "error", err)
		}
	})
}

func validDropboxSignature(secret string, body []byte, signature string) bool {
	provided, err := hex.DecodeString(signature)
	if err != nil {
		return false
	}
	mac := hmac.New(sha256.New, []byte(secret))
	_, _ = mac.Write(body)
	return hmac.Equal(provided, mac.Sum(nil))
}

type syncWorker struct {
	triggers chan struct{}
	done     chan struct{}
}

func startSyncWorker(
	ctx context.Context,
	dropboxSyncer *syncer.Syncer,
	logger *slog.Logger,
) *syncWorker {
	worker := &syncWorker{
		triggers: make(chan struct{}, 1),
		done:     make(chan struct{}),
	}
	go worker.run(ctx, dropboxSyncer, logger)
	return worker
}

func (w *syncWorker) Trigger() {
	select {
	case w.triggers <- struct{}{}:
	default:
	}
}

func (w *syncWorker) Done() <-chan struct{} {
	return w.done
}

func (w *syncWorker) run(
	ctx context.Context,
	dropboxSyncer *syncer.Syncer,
	logger *slog.Logger,
) {
	defer close(w.done)

	var timer *time.Timer
	var timerC <-chan time.Time
	for {
		select {
		case <-ctx.Done():
			if timer != nil {
				timer.Stop()
			}
			return
		case <-w.triggers:
			if timer == nil {
				timer = time.NewTimer(syncDebounce)
			} else {
				if !timer.Stop() {
					select {
					case <-timer.C:
					default:
					}
				}
				timer.Reset(syncDebounce)
			}
			timerC = timer.C
		case <-timerC:
			timerC = nil
			logger.Info("Starting Dropbox synchronization")
			if err := dropboxSyncer.SyncAll(ctx); err != nil {
				logger.Error("Dropbox synchronization failed; retrying", "error", err)
				timer.Reset(syncRetryDelay)
				timerC = timer.C
			}
		}
	}
}

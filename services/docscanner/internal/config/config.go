package config

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/joho/godotenv"
)

type Config struct {
	Port             string
	DBPath           string
	DownloadDir      string
	DropboxAppKey    string
	DropboxAppSecret string
	DropboxToken     string
	GeminiAPIKey     string
	ServiceDir       string
	InDocker         bool
}

func Load() (Config, error) {
	inDocker := isDocker()
	serviceDir, err := findServiceDir()
	if err != nil {
		return Config{}, err
	}

	if !inDocker {
		if err := loadDotEnv(serviceDir); err != nil {
			return Config{}, err
		}
	}

	dbPath := strings.TrimSpace(os.Getenv("DB_PATH"))
	if dbPath == "" {
		if inDocker {
			dbPath = "/app/db_volume/db.sqlite3"
		} else {
			dbPath = filepath.Join("..", "..", "db_volume", "db.sqlite3")
		}
	}

	downloadDir := strings.TrimSpace(os.Getenv("DOWNLOAD_DIR"))
	if downloadDir == "" {
		if inDocker {
			downloadDir = "/app/downloads"
		} else {
			downloadDir = filepath.Join("..", "..", "media", "dropbox")
		}
	}

	dbPath, err = resolvePath(serviceDir, dbPath)
	if err != nil {
		return Config{}, fmt.Errorf("resolve database path: %w", err)
	}
	downloadDir, err = resolvePath(serviceDir, downloadDir)
	if err != nil {
		return Config{}, fmt.Errorf("resolve download directory: %w", err)
	}
	if err := os.MkdirAll(downloadDir, 0o755); err != nil {
		return Config{}, fmt.Errorf("create download directory: %w", err)
	}

	port := strings.TrimSpace(os.Getenv("PORT"))
	if port == "" {
		port = "8080"
	}

	return Config{
		Port:             port,
		DBPath:           dbPath,
		DownloadDir:      downloadDir,
		DropboxAppKey:    strings.TrimSpace(os.Getenv("DROPBOX_APP_KEY")),
		DropboxAppSecret: strings.TrimSpace(os.Getenv("DROPBOX_APP_SECRET")),
		DropboxToken:     strings.TrimSpace(os.Getenv("DROPBOX_REFRESH_TOKEN")),
		GeminiAPIKey:     strings.TrimSpace(os.Getenv("GEMINI_API_KEY")),
		ServiceDir:       serviceDir,
		InDocker:         inDocker,
	}, nil
}

func isDocker() bool {
	if value := strings.TrimSpace(os.Getenv("DOCKER_CONTAINER")); value == "1" || strings.EqualFold(value, "true") {
		return true
	}
	_, err := os.Stat("/.dockerenv")
	return err == nil
}

func findServiceDir() (string, error) {
	cwd, err := os.Getwd()
	if err != nil {
		return "", fmt.Errorf("get working directory: %w", err)
	}

	for dir := cwd; ; dir = filepath.Dir(dir) {
		if filepath.Base(dir) == "docscanner" {
			return filepath.Abs(dir)
		}
		for _, candidate := range []string{
			filepath.Join(dir, "services", "docscanner"),
			filepath.Join(dir, "docscanner"),
		} {
			if info, statErr := os.Stat(candidate); statErr == nil && info.IsDir() {
				return filepath.Abs(candidate)
			}
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			break
		}
	}

	return filepath.Abs(cwd)
}

func loadDotEnv(serviceDir string) error {
	localEnv := filepath.Join(serviceDir, ".env")
	rootEnv := filepath.Join(serviceDir, "..", "..", ".env")

	for _, path := range []string{localEnv, rootEnv} {
		_, err := os.Stat(path)
		if err == nil {
			if loadErr := godotenv.Load(path); loadErr != nil {
				return fmt.Errorf("load environment file %q: %w", path, loadErr)
			}
			continue
		}
		if !errors.Is(err, os.ErrNotExist) {
			return fmt.Errorf("access environment file %q: %w", path, err)
		}
	}
	return nil
}

func resolvePath(baseDir, value string) (string, error) {
	if !filepath.IsAbs(value) {
		value = filepath.Join(baseDir, value)
	}
	return filepath.Abs(filepath.Clean(value))
}

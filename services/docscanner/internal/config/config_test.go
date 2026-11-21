package config

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLoadDotEnvPrefersServiceEnvironmentFile(t *testing.T) {
	root := t.TempDir()
	serviceDir := filepath.Join(root, "services", "docscanner")
	if err := os.MkdirAll(serviceDir, 0o755); err != nil {
		t.Fatal(err)
	}
	writeEnvFile(t, filepath.Join(root, ".env"), "DOCSCANNER_TEST_VALUE=root\nROOT_ONLY_VALUE=root\n")
	writeEnvFile(t, filepath.Join(serviceDir, ".env"), "DOCSCANNER_TEST_VALUE=service\n")

	unsetEnv(t, "DOCSCANNER_TEST_VALUE")
	unsetEnv(t, "ROOT_ONLY_VALUE")
	if err := loadDotEnv(serviceDir); err != nil {
		t.Fatal(err)
	}
	if got := os.Getenv("DOCSCANNER_TEST_VALUE"); got != "service" {
		t.Fatalf("loaded value = %q, want service", got)
	}
	if got := os.Getenv("ROOT_ONLY_VALUE"); got != "root" {
		t.Fatalf("root-only value = %q, want root", got)
	}
}

func TestLoadDotEnvFallsBackToRepositoryEnvironmentFile(t *testing.T) {
	root := t.TempDir()
	serviceDir := filepath.Join(root, "services", "docscanner")
	if err := os.MkdirAll(serviceDir, 0o755); err != nil {
		t.Fatal(err)
	}
	writeEnvFile(t, filepath.Join(root, ".env"), "DOCSCANNER_TEST_VALUE=root\n")

	unsetEnv(t, "DOCSCANNER_TEST_VALUE")
	if err := loadDotEnv(serviceDir); err != nil {
		t.Fatal(err)
	}
	if got := os.Getenv("DOCSCANNER_TEST_VALUE"); got != "root" {
		t.Fatalf("loaded value = %q, want root", got)
	}
}

func TestResolvePathUsesServiceDirectory(t *testing.T) {
	baseDir := t.TempDir()
	got, err := resolvePath(baseDir, filepath.Join("..", "media", "dropbox"))
	if err != nil {
		t.Fatal(err)
	}
	want, err := filepath.Abs(filepath.Join(baseDir, "..", "media", "dropbox"))
	if err != nil {
		t.Fatal(err)
	}
	if got != want {
		t.Fatalf("resolved path = %q, want %q", got, want)
	}
}

func TestLoadUsesLocalDefaultsAndCreatesDownloadDirectory(t *testing.T) {
	if isDocker() {
		t.Skip("local path defaults apply outside Docker")
	}

	root := t.TempDir()
	serviceDir := filepath.Join(root, "services", "docscanner")
	if err := os.MkdirAll(serviceDir, 0o755); err != nil {
		t.Fatal(err)
	}
	writeEnvFile(t, filepath.Join(serviceDir, ".env"), "PORT=8123\nGEMINI_API_KEY=test-key\n")

	for _, key := range []string{
		"DOCKER_CONTAINER",
		"PORT",
		"DB_PATH",
		"DOWNLOAD_DIR",
		"DROPBOX_APP_KEY",
		"DROPBOX_APP_SECRET",
		"DROPBOX_REFRESH_TOKEN",
		"GEMINI_API_KEY",
	} {
		unsetEnv(t, key)
	}

	oldDir, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Chdir(serviceDir); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if err := os.Chdir(oldDir); err != nil {
			t.Errorf("restore working directory: %v", err)
		}
	})

	cfg, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Port != "8123" {
		t.Fatalf("port = %q, want 8123", cfg.Port)
	}
	if cfg.GeminiAPIKey != "test-key" {
		t.Fatalf("Gemini API key = %q, want configured key", cfg.GeminiAPIKey)
	}
	wantDB := filepath.Join(root, "db_volume", "db.sqlite3")
	if cfg.DBPath != wantDB {
		t.Fatalf("database path = %q, want %q", cfg.DBPath, wantDB)
	}
	wantDownloads := filepath.Join(root, "media", "dropbox")
	if cfg.DownloadDir != wantDownloads {
		t.Fatalf("download directory = %q, want %q", cfg.DownloadDir, wantDownloads)
	}
	if info, err := os.Stat(cfg.DownloadDir); err != nil || !info.IsDir() {
		t.Fatalf("download directory was not created: info=%v error=%v", info, err)
	}
}

func writeEnvFile(t *testing.T, path, contents string) {
	t.Helper()
	if err := os.WriteFile(path, []byte(contents), 0o600); err != nil {
		t.Fatal(err)
	}
}

func unsetEnv(t *testing.T, key string) {
	t.Helper()
	old, existed := os.LookupEnv(key)
	if err := os.Unsetenv(key); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if existed {
			_ = os.Setenv(key, old)
		} else {
			_ = os.Unsetenv(key)
		}
	})
}

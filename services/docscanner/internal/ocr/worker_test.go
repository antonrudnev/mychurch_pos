package ocr

import (
	"path/filepath"
	"testing"
)

func TestResolveLocalFileUsesDownloadDirectoryAndRejectsTraversal(t *testing.T) {
	root := t.TempDir()
	path, err := resolveLocalFile(root, "dropbox/product_report/report.pdf")
	if err != nil {
		t.Fatal(err)
	}
	if want := filepath.Join(root, "product_report", "report.pdf"); path != want {
		t.Fatalf("resolved path = %q, want %q", path, want)
	}

	for _, localFile := range []string{
		"dropbox/../secrets.txt",
		"other/report.pdf",
		filepath.Join(root, "report.pdf"),
	} {
		if _, err := resolveLocalFile(root, localFile); err == nil {
			t.Errorf("resolveLocalFile(%q) succeeded, want error", localFile)
		}
	}
}

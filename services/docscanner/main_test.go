package main

import (
	"bytes"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestDropboxWebhookVerifiesSignatureAndTriggersSync(t *testing.T) {
	const secret = "test-secret"
	body := []byte(`{"list_folder":{"accounts":["dbid:account"]}}`)
	mac := hmac.New(sha256.New, []byte(secret))
	_, _ = mac.Write(body)
	signature := hex.EncodeToString(mac.Sum(nil))

	triggered := 0
	handler := newWebhookHandler(secret, func() {
		triggered++
	}, slog.New(slog.NewTextHandler(io.Discard, nil)))

	request := httptest.NewRequest(http.MethodPost, "/webhook", bytes.NewReader(body))
	request.Header.Set("X-Dropbox-Signature", signature)
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	if response.Code != http.StatusOK || response.Body.String() != "OK" {
		t.Fatalf("response = %d %q, want 200 OK", response.Code, response.Body.String())
	}
	if triggered != 1 {
		t.Fatalf("trigger count = %d, want 1", triggered)
	}

	request = httptest.NewRequest(http.MethodPost, "/webhook", bytes.NewReader(body))
	request.Header.Set("X-Dropbox-Signature", "invalid")
	response = httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	if response.Code != http.StatusUnauthorized {
		t.Fatalf("invalid signature response = %d, want 401", response.Code)
	}
	if triggered != 1 {
		t.Fatalf("invalid request triggered sync, count = %d", triggered)
	}
}

func TestWebhookChallengeResponse(t *testing.T) {
	request := httptest.NewRequest(http.MethodGet, "/webhook?challenge=dropbox-challenge", nil)
	response := httptest.NewRecorder()
	handleWebhookChallenge(response, request)

	if response.Code != http.StatusOK || response.Body.String() != "dropbox-challenge" {
		t.Fatalf("challenge response = %d %q", response.Code, response.Body.String())
	}
	if got := response.Header().Get("Content-Type"); got != "text/plain" {
		t.Fatalf("Content-Type = %q, want text/plain", got)
	}
	if got := response.Header().Get("X-Content-Type-Options"); got != "nosniff" {
		t.Fatalf("X-Content-Type-Options = %q, want nosniff", got)
	}
}

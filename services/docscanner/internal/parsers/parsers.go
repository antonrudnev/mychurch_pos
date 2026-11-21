package parsers

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"

	"docscanner/internal/storage"
	"google.golang.org/genai"
)

type Parser interface {
	SystemInstruction([]storage.CatalogItem) string
	ResponseSchema() *genai.Schema
	Parse([]byte, []storage.CatalogItem) ([]storage.IncomingTransaction, error)
}

type Registry struct {
	parsers map[string]Parser
}

func NewRegistry() *Registry {
	return &Registry{parsers: map[string]Parser{
		"product_report": ProductReportParser{},
		"candle_report":  CandleReportParser{},
	}}
}

func (r *Registry) For(documentType string) (Parser, error) {
	parser, ok := r.parsers[documentType]
	if !ok {
		return nil, fmt.Errorf("unsupported document type %q", documentType)
	}
	return parser, nil
}

func decodeResponse(data []byte, target any) error {
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil {
		return fmt.Errorf("decode Gemini JSON response: %w", err)
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		if err == nil {
			return errors.New("decode Gemini JSON response: unexpected second JSON value")
		}
		return fmt.Errorf("decode trailing Gemini response data: %w", err)
	}
	return nil
}

func normalizedName(value string) string {
	var normalized strings.Builder
	for _, character := range strings.ToUpper(value) {
		if unicode.IsSpace(character) || character == '-' || character == '\u2010' ||
			character == '\u2011' || character == '\u2012' || character == '\u2013' ||
			character == '\u2014' {
			continue
		}
		normalized.WriteRune(character)
	}
	return normalized.String()
}

func normalizedDate(value string) string {
	value = strings.TrimSpace(value)
	if value == "" {
		return ""
	}
	date, err := time.Parse("2006-01-02", value)
	if err != nil {
		return ""
	}
	return date.Format("2006-01-02")
}

func sumCounts(counts []int) int64 {
	var total int64
	for _, count := range counts {
		total += int64(count)
	}
	return total
}

func boundedRawName(value string) string {
	if utf8.RuneCountInString(value) <= 255 {
		return value
	}
	runes := []rune(value)
	return string(runes[:255])
}

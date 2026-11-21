package parsers

import (
	"encoding/json"
	"testing"

	"docscanner/internal/storage"
)

func TestProductReportParseMatchesNormalizedNameAndPrice(t *testing.T) {
	catalog := []storage.CatalogItem{
		{ID: 1, ItemType: "goods", Name: "ИК-92", Price: 25},
		{ID: 2, ItemType: "goods", Name: "ИК 92", Price: 40},
		{ID: 3, ItemType: "candle", Name: "Свеча 40", Price: 40},
	}
	response := []byte(`{
		"report_date":"2026-10-30",
		"rows":[
			{"raw_name":"ИК 92","counts":[1,1,1,2],"price":40},
		{"raw_name":"ИК92","counts":[1],"price":99},
			{"raw_name":"unknown","counts":[0,-1],"price":0}
		]
	}`)

	transactions, err := (ProductReportParser{}).Parse(response, catalog)
	if err != nil {
		t.Fatal(err)
	}
	if len(transactions) != 2 {
		t.Fatalf("transaction count = %d, want 2", len(transactions))
	}
	row := transactions[0]
	if row.ItemID == nil || *row.ItemID != 2 {
		t.Fatalf("item ID = %v, want 2", row.ItemID)
	}
	if row.Quantity != 5 || row.Price != 40 || row.ReportDate != "2026-10-30" {
		t.Fatalf("parsed transaction = %#v", row)
	}
	var rawCounts []any
	if err := json.Unmarshal(row.RawCounts, &rawCounts); err != nil {
		t.Fatal(err)
	}
	if len(rawCounts) != 2 || rawCounts[1] != float64(40) {
		t.Fatalf("raw counts = %s, want counts and price", row.RawCounts)
	}
	if transactions[1].ItemID != nil {
		t.Fatalf("item ID for unmatched duplicate price = %v, want nil", transactions[1].ItemID)
	}
}

func TestProductReportUsesCatalogPriceAndNullDateWhenUnreadable(t *testing.T) {
	transactions, err := (ProductReportParser{}).Parse([]byte(`{
		"report_date":"not a date",
		"rows":[{"raw_name":"0-123","counts":[2],"price":0}]
	}`), []storage.CatalogItem{
		{ID: 8, ItemType: "goods", Name: "0123", Price: 12.5},
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(transactions) != 1 {
		t.Fatalf("transaction count = %d, want 1", len(transactions))
	}
	if transactions[0].ReportDate != "" || transactions[0].Price != 12.5 {
		t.Fatalf("date/price = %q/%v", transactions[0].ReportDate, transactions[0].Price)
	}
}

func TestCandleReportUsesReportedTotalOrCounts(t *testing.T) {
	transactions, err := (CandleReportParser{}).Parse([]byte(`{
		"report_date":"2026-10-30",
		"rows":[
			{"denomination":20,"counts":[2,5,8,1],"reported_total":20},
			{"denomination":35,"counts":[2,3],"reported_total":0},
			{"denomination":45,"counts":[],"reported_total":0}
		]
	}`), []storage.CatalogItem{
		{ID: 20, ItemType: "candle", Handle: "candle-20"},
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(transactions) != 2 {
		t.Fatalf("transaction count = %d, want 2", len(transactions))
	}
	if transactions[0].Quantity != 20 || transactions[0].Price != 20 ||
		transactions[0].ItemID == nil || *transactions[0].ItemID != 20 {
		t.Fatalf("reported-total row = %#v", transactions[0])
	}
	if transactions[1].Quantity != 5 || transactions[1].ItemID != nil ||
		transactions[1].RawName != "Свеча 35" {
		t.Fatalf("counts-only row = %#v", transactions[1])
	}
	if string(transactions[1].RawCounts) != "[2,3]" {
		t.Fatalf("raw counts = %s, want [2,3]", transactions[1].RawCounts)
	}
}

func TestRegistryRejectsUnknownDocumentType(t *testing.T) {
	if _, err := NewRegistry().For("unknown"); err == nil {
		t.Fatal("expected unsupported document type error")
	}
}

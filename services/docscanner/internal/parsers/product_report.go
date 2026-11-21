package parsers

import (
	"encoding/json"
	"fmt"
	"math"
	"strings"

	"docscanner/internal/storage"

	"google.golang.org/genai"
)

type ProductReportParser struct{}

type productReportResponse struct {
	ReportDate string              `json:"report_date"`
	Rows       []productReportItem `json:"rows"`
}

type productReportItem struct {
	RawName string  `json:"raw_name"`
	Counts  []int   `json:"counts"`
	Price   float64 `json:"price"`
}

func (ProductReportParser) SystemInstruction(catalog []storage.CatalogItem) string {
	var items strings.Builder
	for _, item := range catalog {
		if item.ItemType == "candle" {
			continue
		}
		fmt.Fprintf(&items, "- Артикул: %q; цена за единицу: %.2f\n", item.Name, item.Price)
	}
	return "Ты распознаёшь товарную ведомость на изображении или PDF. " +
		"Верни report_date в формате YYYY-MM-DD. Для диапазона дат используй конечную дату; " +
		"если дата не читается, верни пустую строку. Для каждой строки таблицы верни raw_name " +
		"(артикул), counts (все отдельные числа из столбца КОЛ-ВО: например, 1+1+1+2 => " +
		"[1,1,1,2], а 2 => [2]) и price (цена за единицу из столбца ЦЕНА). Столбец СУММА " +
		"игнорируй. Если цена неразборчива, используй цену артикула из справочника ниже. " +
		"Не добавляй промежуточные итоги или итоговые суммы в counts.\n\n" +
		"Активные товары (name — артикул, price — цена):\n" + items.String()
}

func (ProductReportParser) ResponseSchema() *genai.Schema {
	return &genai.Schema{
		Type: genai.TypeObject,
		Properties: map[string]*genai.Schema{
			"report_date": {Type: genai.TypeString, Description: "Дата YYYY-MM-DD или пустая строка"},
			"rows": {
				Type: genai.TypeArray,
				Items: &genai.Schema{
					Type: genai.TypeObject,
					Properties: map[string]*genai.Schema{
						"raw_name": {Type: genai.TypeString},
						"counts":   {Type: genai.TypeArray, Items: &genai.Schema{Type: genai.TypeInteger}},
						"price":    {Type: genai.TypeNumber},
					},
					Required: []string{"raw_name", "counts", "price"},
				},
			},
		},
		Required:         []string{"report_date", "rows"},
		PropertyOrdering: []string{"report_date", "rows"},
	}
}

func (ProductReportParser) Parse(
	data []byte,
	catalog []storage.CatalogItem,
) ([]storage.IncomingTransaction, error) {
	var response productReportResponse
	if err := decodeResponse(data, &response); err != nil {
		return nil, err
	}
	itemsByName := make(map[string][]storage.CatalogItem)
	for _, item := range catalog {
		if item.ItemType == "candle" {
			continue
		}
		name := normalizedName(item.Name)
		if name != "" {
			itemsByName[name] = append(itemsByName[name], item)
		}
	}

	transactions := make([]storage.IncomingTransaction, 0, len(response.Rows))
	for _, row := range response.Rows {
		quantity := sumCounts(row.Counts)
		if quantity <= 0 {
			continue
		}

		var itemID *int64
		price := row.Price
		matches := itemsByName[normalizedName(row.RawName)]
		var matchedItem *storage.CatalogItem
		if len(matches) == 1 {
			matchedItem = &matches[0]
		} else if len(matches) > 1 && row.Price > 0 {
			for index := range matches {
				if math.Abs(matches[index].Price-row.Price) < 0.005 {
					matchedItem = &matches[index]
					break
				}
			}
		}
		if matchedItem != nil {
			itemID = &matchedItem.ID
			if price <= 0 {
				price = matchedItem.Price
			}
		}
		if price < 0 || math.IsNaN(price) || math.IsInf(price, 0) {
			price = 0
		}
		rawCounts, err := json.Marshal(row.Counts)
		if err != nil {
			return nil, fmt.Errorf("encode product raw counts: %w", err)
		}
		transactions = append(transactions, storage.IncomingTransaction{
			ReportDate: normalizedDate(response.ReportDate),
			ItemID:     itemID,
			Price:      price,
			Quantity:   quantity,
			RawName:    boundedRawName(row.RawName),
			RawCounts:  rawCounts,
		})
	}
	return transactions, nil
}

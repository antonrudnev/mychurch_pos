package parsers

import (
	"encoding/json"
	"fmt"

	"docscanner/internal/storage"

	"google.golang.org/genai"
)

type CandleReportParser struct{}

type candleReportResponse struct {
	ReportDate string             `json:"report_date"`
	Rows       []candleReportItem `json:"rows"`
}

type candleReportItem struct {
	Denomination  int   `json:"denomination"`
	Counts        []int `json:"counts"`
	ReportedTotal int   `json:"reported_total"`
}

func (CandleReportParser) SystemInstruction(catalog []storage.CatalogItem) string {
	denominations := make([]string, 0, len(catalog))
	for _, item := range catalog {
		if item.ItemType == "candle" {
			denominations = append(denominations, fmt.Sprintf("%s (%.2f)", item.Handle, item.Price))
		}
	}
	return "Ты распознаёшь свечную ведомость на изображении или PDF.\n" +
		"1. Верни report_date в формате YYYY-MM-DD (для диапазона дат вроде '15-20 ноябрь 2026' " +
		"используй конечную дату '2026-11-20', если дата не читается — пустую строку).\n" +
		"2. Структура таблицы: слева указан печатный номинал свечи (denomination), в центре записаны " +
		"отдельные количества проданных свечей (через запятую, точку с запятой, пробел или в несколько строк), " +
		"а справа находятся ДВЕ итоговые колонки:\n" +
		"   - предпоследняя колонка: итоговое КОЛИЧЕСТВО свечей в штуках (reported_total);\n" +
		"   - самая последняя (крайняя правая) колонка: итоговая СУММА В РУБЛЯХ (количество × номинал) — " +
		"ЭТУ КОЛОНКУ ИГНОРИРУЙ, не записывай сумму в рублях ни в reported_total, ни в counts!\n" +
		"3. В массив counts включай только отдельные единичные числа продаж (не включай промежуточные итоги " +
		"после дефиса вроде '-6' или '-49', а также печатные цифры в пустых строках без продаж).\n" +
		"4. Если на бланке не заполнен столбец с итоговым количеством штук, верни reported_total = 0. " +
		"Пустые строки без продаж не включай.\n" +
		"Доступные номиналы из активного справочника: " + fmt.Sprint(denominations)
}

func (CandleReportParser) ResponseSchema() *genai.Schema {
	return &genai.Schema{
		Type: genai.TypeObject,
		Properties: map[string]*genai.Schema{
			"report_date": {Type: genai.TypeString, Description: "Дата YYYY-MM-DD или пустая строка"},
			"rows": {
				Type: genai.TypeArray,
				Items: &genai.Schema{
					Type: genai.TypeObject,
					Properties: map[string]*genai.Schema{
						"denomination":   {Type: genai.TypeInteger, Description: "Номинал свечи (цена за 1 шт.)"},
						"counts":         {Type: genai.TypeArray, Items: &genai.Schema{Type: genai.TypeInteger}, Description: "Отдельные числа продаж в штуках"},
						"reported_total": {Type: genai.TypeInteger, Description: "Итоговое количество свечей в ШТУКАХ из предпоследней колонки (НЕ сумма в рублях!) или 0"},
					},
					Required: []string{"denomination", "counts", "reported_total"},
				},
			},
		},
		Required:         []string{"report_date", "rows"},
		PropertyOrdering: []string{"report_date", "rows"},
	}
}

func (CandleReportParser) Parse(
	data []byte,
	catalog []storage.CatalogItem,
) ([]storage.IncomingTransaction, error) {
	var response candleReportResponse
	if err := decodeResponse(data, &response); err != nil {
		return nil, err
	}
	itemsByHandle := make(map[string]int64)
	for _, item := range catalog {
		if item.ItemType == "candle" {
			itemsByHandle[item.Handle] = item.ID
		}
	}

	transactions := make([]storage.IncomingTransaction, 0, len(response.Rows))
	for _, row := range response.Rows {
		if row.Denomination <= 0 {
			continue
		}
		quantity := int64(row.ReportedTotal)
		if quantity <= 0 {
			quantity = sumCounts(row.Counts)
		}
		if quantity <= 0 {
			continue
		}
		var itemID *int64
		if id, ok := itemsByHandle[fmt.Sprintf("candle-%d", row.Denomination)]; ok {
			itemID = &id
		}
		rawCounts, err := json.Marshal(row.Counts)
		if err != nil {
			return nil, fmt.Errorf("encode candle raw counts: %w", err)
		}
		transactions = append(transactions, storage.IncomingTransaction{
			ReportDate: normalizedDate(response.ReportDate),
			ItemID:     itemID,
			Price:      float64(row.Denomination),
			Quantity:   quantity,
			RawName:    fmt.Sprintf("Свеча %d", row.Denomination),
			RawCounts:  rawCounts,
		})
	}
	return transactions, nil
}

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
	return "Ты распознаёшь рукописную свечную ведомость на изображении или PDF.\n" +
		"1. ДАТА: Верни report_date в формате YYYY-MM-DD. Для диапазона дат (например, '23-27 ноябрь 2026') " +
		"используй конечную дату ('2026-11-27'). Если дата не читается — верни пустую строку.\n" +
		"2. СТРУКТУРА БЛАНКА:\n" +
		"   - Слева указан печатный номинал свечи (denomination). Один блок номинала может занимать от 1 до 4 горизонтальных строк (например, номинал 20 занимает 4 строки, 35 — 2 строки).\n" +
		"   - В центральной части записаны отдельные количества проданных свечей (целые числа, разделённые запятыми или точками с запятой). Внимание: точки с запятой (;) и запятые не являются цифрами — не путай хвостики от ';' с цифрой 1, а запятые с десятичными точками (числа всегда целые).\n" +
		"   - Справа находятся ДВЕ итоговые колонки (обычно в нижней строке блока номинала):\n" +
		"     * предпоследняя колонка: итоговое КОЛИЧЕСТВО свечей в штуках (reported_total);\n" +
		"     * крайняя правая колонка: итоговая СУММА В РУБЛЯХ (количество × номинал) — ЭТУ КОЛОНКУ ИГНОРИРУЙ.\n" +
		"3. ОСОБЫЕ НИЖНИЕ СТРОКИ (номиналы 200, 250 и т.п.):\n" +
		"   - В нижних строках в центре листа могут быть напечатаны дополнительные номиналы в рамках (например, '150' в строке 200 или '300' в строке 250).\n" +
		"   - Для таких строк итоговое количество (reported_total) и сумма в рублях могут быть вписаны в ячейки СРАЗУ ПЕРЕД этим центральным печатным числом (например, в строке 200: слева записано '1', далее перед печатным '150' вписаны итоги '1' и '200').\n" +
		"   - Печатные числа внутри таблицы (такие как 150, 300) являются заголовками других номиналов — НИКОГДА не включай их в counts или reported_total.\n" +
		"4. ПРАВИЛА СБОРА ДАННЫХ:\n" +
		"   - В массив counts включай только рукописные отдельные числа продаж (не включай промежуточные итоги после дефиса вроде '-6' или '-49').\n" +
		"   - Не пересчитывай reported_total самостоятельно, даже если сумма элементов counts отличается на 1–2 единицы из-за ошибки подсчёта на бланке — бери строго то число, которое вписано в ячейку итогового количества. Если ячейка итогового количества пуста, верни reported_total = 0.\n" +
		"   - Пустые строки без рукописных продаж не включай в результат.\n" +
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

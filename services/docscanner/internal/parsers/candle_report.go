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
		"2. СТРУКТУРА БЛАНКА И ПРАВИЛО ДВУХ ИТОГОВЫХ КЛЕТОК:\n" +
		"   - Слева указан печатный номинал свечи (denomination). Один блок номинала может занимать от 1 до 4 горизонтальных строк (например, 20 — 4 строки, 35 — 2 строки).\n" +
		"   - Внутри рабочей области записываются отдельные количества проданных свечей (целые числа, разделённые запятыми или точками с запятой). Внимание: точки с запятой (;) и запятые — это разделители, не путай хвостики от ';' с цифрой 1, а запятые с десятичными точками.\n" +
		"   - КАЖДЫЙ сегмент номинала (в конце всей строки или в конце своей половины строки) заканчивается ДВУМЯ итоговыми клетками подряд:\n" +
		"     1) Первая клетка (ПОМЕНЬШЕ / поуже) — итоговое КОЛИЧЕСТВО свечей в штуках (reported_total).\n" +
		"     2) Вторая клетка (ПОБОЛЬШЕ / пошире) — итоговая СУММА В РУБЛЯХ (количество × номинал) — ЭТУ КЛЕТКУ ВСЕГДА ИГНОРИРУЙ, не включай её ни в reported_total, ни в counts.\n" +
		"3. РАЗДЕЛЁННЫЕ НИЖНИЕ СТРОКИ (2 номинала в одной строке, в том числе расчерченные вручную):\n" +
		"   - Нижние строки (например, 200, 250) могут быть разделены по горизонтали на ДВЕ независимые части (левую и правую) для двух разных номиналов.\n" +
		"   - ВНИМАНИЕ НА РУЧНУЮ РАЗЛИНОВКУ: такое разделение может быть НЕ напечатано типографски, а нарисовано ВРУЧНУЮ (ручкой или карандашом) тонкими, менее жирными или неровными вертикальными линиями прямо внутри строки.\n" +
		"   - Левая часть относится к номиналу у левого края бланка и заканчивается своей парой итоговых клеток (узкая — штуки, широкая — сумма в рублях), выделенных типографскими или нарисованными от руки вертикальными линиями, прямо перед началом второго номинала.\n" +
		"   - Сразу после широкой итоговой клетки левой части идёт заголовок ВТОРОГО номинала (он может быть напечатан типографским шрифтом, как '150' или '300', а может быть ВПИСАН ОТ РУКИ), далее — его продажи и в самом конце строки справа — его собственная пара итоговых клеток (узкая — штуки, широкая — сумма).\n" +
		"   - НИКОГДА не принимай заголовок второго номинала (ни печатный, ни вписанный от руки после ручной разделительной линии) за продажу или итог первого номинала.\n" +
		"4. ПРАВИЛА СБОРА ДАННЫХ:\n" +
		"   - В массив counts включай только отдельные числа продаж (не включай промежуточные итоги после дефиса вроде '-6' или '-49').\n" +
		"   - Не пересчитывай reported_total самостоятельно, даже если сумма элементов counts расходится на 1–2 единицы — бери строго число из узкой итоговой клетки. Если узкая итоговая клетка пуста, верни reported_total = 0.\n" +
		"   - Пустые номиналы без продаж не включай в результат.\n" +
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

window.addEventListener('load', function() {
    // Находим выпадающий список товара и поле цены на форме Django
    const itemSelect = document.getElementById('id_item');
    const priceInput = document.getElementById('id_price');

    // Безопасно парсим JSON со словарем цен, который мы передали из Python
    // (Django рендерит контекст формы, и мы можем забрать переменную, если обернем её скриптом, 
    // но в данном случае мы сгенерируем данные прямо в DOM-структуру или прочитаем из глобального скрипта)
    
    if (itemSelect && priceInput) {
        itemSelect.addEventListener('change', function() {
            const itemId = this.value;
            
            // Запрашиваем цены из скрытого тега данных, который мы добавим через переопределение шаблона,
            // либо через простой fetch-запрос к БД. 
            // Но чтобы не усложнять, сделаем самый надежный и быстрый способ: fetch-запрос к мини-API.
            if (itemId) {
                // Запрашиваем данные о товаре напрямую у Django админки (встроенный autocomplete эндпоинт или кастомный)
                // Для простоты — сделаем запрос на получение цены
                fetch(`/admin/directory/item/${itemId}/change/`)
                    .then(response => response.text())
                    .then(html => {
                        // Парсим страницу карточки товара, чтобы вытащить его цену
                        const parser = new DOMParser();
                        const doc = parser.parseFromString(html, 'text/html');
                        const itemPriceInput = doc.getElementById('id_price');
                        if (itemPriceInput && itemPriceInput.value) {
                            priceInput.value = itemPriceInput.value;
                        }
                    })
                    .catch(err => console.error('Ошибка автоподстановки цены:', err));
            }
        });
    }
});
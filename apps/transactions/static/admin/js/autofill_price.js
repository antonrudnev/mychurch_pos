window.addEventListener('load', function() {
    const itemSelect = document.getElementById('id_item');
    const priceInput = document.getElementById('id_price');

    if (itemSelect && priceInput) {
        itemSelect.addEventListener('change', function() {
            const itemId = this.value;
            
            if (itemId) {
                fetch(`/admin/directory/item/${itemId}/change/`)
                    .then(response => response.text())
                    .then(html => {
                        const parser = new DOMParser();
                        const doc = parser.parseFromString(html, 'text/html');
                        const itemPriceInput = doc.getElementById('id_price');
                        
                        // Если цена у товара есть, подставляем её. Иначе — очищаем поле для ручного ввода
                        if (itemPriceInput && itemPriceInput.value) {
                            priceInput.value = itemPriceInput.value;
                        } else {
                            priceInput.value = '0.00'; 
                        }
                    })
                    .catch(err => console.error('Ошибка автоподстановки цены:', err));
            }
        });
    }
});
window.addEventListener('load', function() {
    const rows = document.querySelectorAll('#result_list tbody tr');

    rows.forEach(row => {
        const metaSpan = row.querySelector('.item-meta');
        const priceCell = row.querySelector('.field-price');

        if (metaSpan && priceCell) {
            const hasPrice = metaSpan.getAttribute('data-has-price') === 'true';
            const priceInput = priceCell.querySelector('input');

            // Если у товара в базе ИЗНАЧАЛЬНО нет цены
            if (!hasPrice) {
                if (priceInput) {
                    priceInput.value = '';
                    priceInput.style.display = 'none'; // Скрываем инпут ввода
                    
                    const placeholder = document.createElement('span');
                    placeholder.textContent = '(Свободная)';
                    placeholder.style.color = '#999';
                    priceCell.appendChild(placeholder);
                }
            }
        }
    });
});
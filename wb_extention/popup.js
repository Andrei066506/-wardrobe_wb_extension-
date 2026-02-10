document.addEventListener('DOMContentLoaded', async () => {
  const statusEl = document.getElementById('status');
  const generateBtn = document.getElementById('generate');

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

    if (!tab.url || !tab.url.includes('wildberries.ru/catalog/') || !tab.url.includes('/detail.aspx')) {
      statusEl.innerHTML = '❌ Откройте страницу товара на Wildberries.';
      return;
    }

    const product = await chrome.tabs.sendMessage(tab.id, { action: "getProduct" });

    if (!product || !product.name || !product.nm_id) {
      statusEl.innerHTML = '❌ Не удалось определить товар.';
      return;
    }

    statusEl.innerHTML = `Товар: <b>${product.name}</b><br><small>NM ID: ${product.nm_id}</small>`;
    generateBtn.disabled = false;

    generateBtn.onclick = async () => {
      generateBtn.disabled = true;
      generateBtn.textContent = 'Генерируем…';

      try {
        const response = await fetch('http://localhost:5000/api/capsule', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query: product.name })
        });

        if (!response.ok) throw new Error('Сервер вернул ошибку');

        await chrome.tabs.create({ url: 'http://localhost:5000' });
        window.close();
      } catch (err) {
        statusEl.innerHTML = `❌ Ошибка:<br><small>${err.message || 'Не удалось подключиться к серверу'}</small>`;
        generateBtn.textContent = 'Повторить';
        generateBtn.disabled = false;
      }
    };
  } catch (err) {
    statusEl.innerHTML = '❌ Ошибка при получении данных.';
  }
});
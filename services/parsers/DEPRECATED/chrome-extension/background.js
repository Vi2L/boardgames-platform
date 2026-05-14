// Service worker: читает httpOnly куки через chrome.cookies API и отправляет на парсер.
// Запускается автоматически при каждом визите на avito.ru.

const PARSERS_URL = "http://localhost:8001/api/avito/cookies";

async function syncCookies() {
  return new Promise((resolve) => {
    chrome.cookies.getAll({ domain: ".avito.ru" }, async (cookies) => {
      if (!cookies || cookies.length === 0) {
        resolve({ ok: false, error: "no cookies" });
        return;
      }

      // Проверяем наличие ключевых кук Qrator
      const hasAvisc = cookies.some(c => c.name === "_avisc");
      const cookieNames = cookies.map(c => c.name);
      console.log(`[Avito Sync] ${cookies.length} кук, _avisc: ${hasAvisc}, v: ${cookieNames.includes("v")}`);

      try {
        const resp = await fetch(PARSERS_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(cookies),
        });
        const result = await resp.json();
        console.log("[Avito Sync] OK →", result);
        resolve({ ok: true, count: cookies.length, hasAvisc });
      } catch (e) {
        console.warn("[Avito Sync] Ошибка:", e.message);
        resolve({ ok: false, error: e.message });
      }
    });
  });
}

// Синхронизируем при каждом визите на avito.ru (через content.js)
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === "SYNC_COOKIES") {
    syncCookies().then(sendResponse);
    return true; // async response
  }
});

// Синхронизируем и по кнопке в popup
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === "MANUAL_SYNC") {
    syncCookies().then(sendResponse);
    return true;
  }
});

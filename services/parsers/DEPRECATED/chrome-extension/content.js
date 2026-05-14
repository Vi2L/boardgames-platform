// Автоматически синхронизирует куки avito.ru с парсером при каждой загрузке страницы.
// Content script не может читать httpOnly куки — это делает background worker через
// chrome.cookies API. Поэтому content.js только триггерит фоновую синхронизацию.
chrome.runtime.sendMessage({ type: "SYNC_COOKIES" });

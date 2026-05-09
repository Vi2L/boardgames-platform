document.getElementById("btn").addEventListener("click", () => {
  const status = document.getElementById("status");
  status.textContent = "Синхронизирую...";
  chrome.runtime.sendMessage({ type: "MANUAL_SYNC" }, (result) => {
    if (result && result.ok) {
      status.innerHTML = `<span class="ok">✓ Отправлено ${result.count} кук`
        + (result.hasAvisc ? " (включая _avisc)" : " (⚠ нет _avisc)") + `</span>`;
    } else {
      status.innerHTML = `<span class="err">✗ Ошибка: ${result?.error || "неизвестно"}</span>`;
    }
  });
});

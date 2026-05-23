// Auto-refresh del dashboard cada 30s + botón manual de scrape.
(function () {
    const REFRESH_MS = 30_000;

    const btn = document.getElementById('btn-refresh');
    if (btn) {
        btn.addEventListener('click', async () => {
            btn.disabled = true;
            const orig = btn.innerHTML;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Scrapeando...';
            try {
                await fetch('/api/refresh', { method: 'POST' });
            } catch (e) {
                console.error(e);
            } finally {
                window.location.reload();
            }
        });
    }

    // Auto-reload en dashboard y comparativo (no en historial).
    const path = window.location.pathname;
    if (path === '/' || path === '/comparativo' || path === '/buckets' || path === '/matriz') {
        setTimeout(() => window.location.reload(), REFRESH_MS);
    }
})();

// Auto-refresh del dashboard cada 1h + botón manual de scrape.
(function () {
    const REFRESH_MS = 60 * 60 * 1000;
    const REMOTE_POLL_MS = 5000;
    const REMOTE_MAX_WAIT_MS = 4 * 60 * 1000;  // el runner de GitHub tarda ~1-2 min

    // started_at de /api/runs viene sin zona (UTC naive) y con microsegundos:
    // recortar a ms (Safari no parsea mas de 3 decimales) y forzar UTC.
    const parseUtc = (s) => {
        s = s.replace(/(\.\d{3})\d+/, '$1');
        return Date.parse(/Z$|[+-]\d\d:\d\d$/.test(s) ? s : s + 'Z');
    };

    // Espera a que lleguen las tandas de las agencias remotas (GitHub Actions).
    const waitRemote = async (agencies, sinceMs, onTick) => {
        const deadline = Date.now() + REMOTE_MAX_WAIT_MS;
        while (Date.now() < deadline) {
            await new Promise(r => setTimeout(r, REMOTE_POLL_MS));
            onTick(Math.round((deadline - Date.now()) / 1000));
            try {
                const res = await fetch('/api/runs?limit=40');
                const data = await res.json();
                const done = agencies.every(slug => data.runs.some(run =>
                    run.agencia_slug === slug && run.status !== 'running' &&
                    parseUtc(run.started_at) >= sinceMs));
                if (done) return true;
            } catch (e) {
                console.error(e);
            }
        }
        return false;
    };

    const btn = document.getElementById('btn-refresh');
    if (btn) {
        btn.addEventListener('click', async () => {
            btn.disabled = true;
            const spinner = '<span class="spinner-border spinner-border-sm"></span> ';
            btn.innerHTML = spinner + 'Scrapeando...';
            try {
                const res = await fetch('/api/refresh', { method: 'POST' });
                const data = await res.json();
                const agencies = data.remote_agencies || [];
                if (agencies.length && (data.remote === 'dispatched' || data.remote === 'cooldown')) {
                    // cooldown = ya hay una corrida remota en curso (disparada hace <5 min)
                    const since = parseUtc(data.started_at) - (data.remote === 'cooldown' ? 5 * 60 * 1000 : 0);
                    const names = agencies.map(s => s[0].toUpperCase() + s.slice(1)).join(', ');
                    await waitRemote(agencies, since, (secs) => {
                        btn.innerHTML = spinner + `Esperando ${names}... (máx ${secs}s)`;
                    });
                }
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

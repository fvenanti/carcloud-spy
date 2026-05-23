# CarCloudSPY

Monitor en tiempo real de tarifas de rent-a-car en **San Carlos de Bariloche**.

Cada hora consulta las APIs de **ABA**, **Hertz** y **Taraborelli** (Bariloche Aeropuerto), persiste la tarifa en SQLite y muestra un dashboard con histórico, comparativos y matriz cross-agencia.

## Stack

Mismo stack que [CarCloud](../Carcloud-ec2):

- **FastAPI** + **Jinja2 SSR** + **Bootstrap 5** (+ Chart.js para los sparklines)
- **uvicorn** + **Python 3.11-slim** + **Docker compose**
- **SQLite** (cero-config, app aislada)
- **APScheduler** (cron interno cada 1 hora)
- **httpx** + **BeautifulSoup** para los adapters

## Estructura

```
CarCloudSPY/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example
├── main.py                  # FastAPI entry point
├── database.py              # SQLite (agencias, vehiculos, rates, scrape_runs)
├── scheduler.py             # APScheduler — corrida cada 1h
├── shared_templates.py      # Jinja2 + filtros money/dt
├── scrapers/
│   ├── base.py              # interfaz RateAdapter / RateQuote / RateQuery
│   ├── hertz.py             # adapter Hertz (skeleton + demo fallback)
│   ├── localiza.py          # adapter Localiza
│   ├── sixt.py              # adapter Sixt
│   └── taraborelli.py       # adapter Taraborelli
├── routers/
│   ├── dashboard.py         # vistas HTML (/, /historial/...)
│   └── api.py               # endpoints JSON (/api/rates, /api/history, /api/refresh)
├── templates/
│   ├── base.html
│   ├── dashboard.html
│   └── history.html
└── static/
    ├── css/app.css
    └── js/app.js
```

## Setup local

```powershell
# 1. Clonar y entrar al directorio
cd C:\Users\fvena\Desktop\CarCloudSPY

# 2. Crear venv e instalar deps
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 3. Copiar variables de entorno
Copy-Item .env.example .env

# 4. Arrancar
uvicorn main:app --reload --port 8001
```

Abrir [http://localhost:8001](http://localhost:8001).

> Al primer arranque, el scheduler dispara un scrape inmediato. Como los adapters todavía no tienen el endpoint XHR real cableado, devuelven **datos demo** para que el dashboard se vea poblado. Ver sección "Completar adapters" abajo.

## Setup con Docker

```powershell
docker compose up -d --build
```

Levanta en `http://localhost:8001`. Volúmenes mapeados: `data/`, `static/`, `templates/`, `routers/`, `scrapers/` → hot-reload de templates/routers sin rebuild.

## Endpoints

| Ruta | Descripción |
|---|---|
| `GET /` | Dashboard principal (auto-refresh 30s) |
| `GET /historial/{agencia_id}/{vehiculo_id}` | Chart histórico + tabla |
| `GET /api/rates` | JSON con la última tarifa por vehículo |
| `GET /api/history/{agencia_id}/{vehiculo_id}` | JSON histórico (hasta 500 puntos) |
| `GET /api/runs` | JSON con bitácora del scheduler |
| `POST /api/refresh` | Dispara un scrape manual |

## Completar adapters (importante)

Los 4 adapters actualmente devuelven **datos demo** porque las APIs reales son SPAs con endpoints XHR que cambian. Para cablear el adapter real de un sitio:

1. Abrir el sitio en Chrome → DevTools → **Network → XHR**
2. Hacer una búsqueda con fechas de pickup/dropoff Bariloche (BRC)
3. Identificar el XHR que devuelve la lista de vehículos + precios
4. Copiar URL + headers + payload
5. Replicar en `_fetch_live(...)` del adapter correspondiente con `self._client.post(...)`
6. Mapear la respuesta a una lista de `RateQuote`

Taraborelli probablemente tenga HTML server-rendered → parsear con `BeautifulSoup` la página de tarifas.

## Deploy en producción (EC2)

**URL pública:** https://spy.aba.benvert.com.ar
**Repo:** https://github.com/fvenanti/carcloud-spy
**Dir en EC2:** `/home/ubuntu/carcloudspy/`
**Puerto interno:** `127.0.0.1:8004` (bind a localhost — solo accesible vía nginx)
**Nginx site:** `/etc/nginx/sites-available/carcloudspy` → server_name `spy.aba.benvert.com.ar`
**Cert SSL:** Let's Encrypt, renovación automática vía `certbot.timer`

### Flujo de deploy

```powershell
# Local
git add . ; git commit -m "..." ; git push origin main
```

```bash
# EC2
ssh -i C:\Users\fvena\.ssh\carcloud_aba.pem ubuntu@98.88.118.221
cd /home/ubuntu/carcloudspy
git pull origin main

# Si solo cambiaron templates/static/routers/scrapers -> ya esta activo (volumen)
# Si cambio main.py / database.py / scheduler.py / requirements.txt -> rebuild:
sudo docker compose up -d --build
```

### Comandos útiles

```bash
# logs en vivo
sudo docker logs carcloudspy -f

# restart sin rebuild
sudo docker compose restart

# ver scrapeos recientes
curl -s http://127.0.0.1:8004/api/runs | python3 -m json.tool | head -40

# forzar scrape manual
curl -X POST http://127.0.0.1:8004/api/refresh
```

## Variables de entorno

| Var | Default | Descripción |
|---|---|---|
| `SCRAPE_INTERVAL_MIN` | 60 | Frecuencia del scheduler en minutos |
| `PICKUP_LOCATION` | BRC | Código IATA de la sucursal |
| `PICKUP_DAYS_AHEAD` | 7 | Días desde hoy hasta el pickup |
| `RENTAL_DAYS` | 3 | Duración del alquiler a cotizar |
| `HTTP_TIMEOUT` | 20 | Timeout HTTP en segundos |
| `LOG_LEVEL` | INFO | DEBUG/INFO/WARNING/ERROR |
| `TZ` | America/Argentina/Buenos_Aires | Timezone del proceso |

## Próximos pasos sugeridos

- Cablear endpoints XHR reales de los 4 adapters.
- Sumar alertas Telegram cuando un precio cambia más de X% (reutilizando `telegram_notify.py` de CarCloud).
- Vista comparativa cross-agencia por categoría (Económico, SUV, Pickup…).
- Export CSV/Excel del histórico.
- Detección de "tarifa más baja" del día por categoría.

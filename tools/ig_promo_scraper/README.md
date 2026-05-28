# IG Promo Scraper (cliente local Windows)

Scrapea diariamente los perfiles de IG de las 4 agencias y POSTea los posts al
endpoint `/api/promos/ingest_ig` de CarCloudSPY para que el server detecte
promos.

Por qué local: Instagram bloquea servidores headless (recaptcha). Solucion =
Chrome real con tu cuenta. Vive en tu Windows, no en EC2.

---

## Setup (1 sola vez)

### 1. Perfil de Chrome dedicado

Carpeta:

```
%LOCALAPPDATA%\CarCloudSPY\chrome_profile
```

La crea el `run.ps1` la primera vez que corra. Es un perfil **aislado** de tu
Chrome personal — la cookie de IG queda ahí.

### 2. Login inicial (manual, una vez)

Abrí Chrome **visible** apuntando a IG con ese perfil:

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --user-data-dir="$env:LOCALAPPDATA\CarCloudSPY\chrome_profile" `
  --no-first-run --no-default-browser-check `
  "https://www.instagram.com/accounts/login/"
```

Logueate. Cuando IG te muestre "Guardar info" → *Ahora no*. "Activar
notificaciones" → *Ahora no*. Confirmá que ves el feed. Cerrá la ventana.

A partir de acá las corridas automáticas usan ese perfil sin pedir login.

### 3. Token de ingest

En el servidor:

```bash
python -c "import secrets; print(secrets.token_urlsafe(24))"
```

Pegalo en `.env` del server como `PROMO_INGEST_TOKEN=…` y `docker compose up -d --force-recreate`.

El **mismo valor** va como env var en tu Windows (User Environment Variables):

| Var | Valor |
|---|---|
| `CARCLOUDSPY_BASE_URL`    | `https://spy.aba.benvert.com.ar` |
| `CARCLOUDSPY_PROMO_TOKEN` | el token generado |

(Las setea con `setx` o desde *Sistema → Variables de entorno*. `setx` requiere
abrir una shell nueva después.)

### 4. Tarea Programada (diaria)

Abrí *Programador de tareas* → *Crear tarea*.

**General**:
- Nombre: `CarCloudSPY IG Promos`
- *Ejecutar tanto si el usuario inició sesión como si no*
- *Ejecutar con los privilegios más altos*

**Desencadenadores** → *Nuevo*:
- Diariamente, hora 09:05.

**Acciones** → *Nuevo*:
- Programa: `powershell.exe`
- Argumentos:
  `-NoProfile -ExecutionPolicy Bypass -File "%USERPROFILE%\Desktop\CarCloudSPY\tools\ig_promo_scraper\run.ps1"`

(Ajustá la ruta al repo si lo moves.)

**Condiciones**: destildá *iniciar solo si está conectada a la corriente alterna*
si querés que corra en batería.

---

## Correr a mano (test)

```powershell
$env:CARCLOUDSPY_BASE_URL    = "https://spy.aba.benvert.com.ar"
$env:CARCLOUDSPY_PROMO_TOKEN = "<el token>"
& "$pwd\tools\ig_promo_scraper\run.ps1"
```

Output completo en `%LOCALAPPDATA%\CarCloudSPY\logs\ig-YYYYMMDD.log`.

---

## Que pasa si la cookie de IG caduca

`scrape_ig.py` detecta el bounce a `/accounts/login`, loguea y sigue con la
proxima agencia. Vas a ver en el log:

```
WARNING   abarentacar: login redirect persistente, salteo
```

Solución: repetir el paso 2 (login manual visible) para refrescar la sesion.
Suele durar semanas / meses si IG no te flaggea.

---

## Troubleshooting

| Sintoma | Causa probable | Fix |
|---|---|---|
| `CDP no respondio en 15s` | Chrome no arrancó (binario movido / matando otro Chrome con mismo perfil) | Cerrá cualquier Chrome con ese profile, revisá la ruta `$ChromeExe` en `run.ps1`. |
| `unauthorized` en POST | Token desincronizado entre Windows y server | Re-pegá `PROMO_INGEST_TOKEN` en ambos lados. |
| `503 ingest disabled` | Server no tiene `PROMO_INGEST_TOKEN` seteado | Agregalo al `.env` y `docker compose up -d --force-recreate`. |
| Posts no aparecen en `/promos` | Caption no matcheo el detector (server-side) | Revisá `raw_text` en DB, ajustá regex en `scrapers/promos.py`. |

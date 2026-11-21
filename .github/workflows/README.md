# Automatización del Diario

Desde noviembre de 2026 el Diario se arma y se publica solo desde GitHub, sin depender de la PC
(decisión del 21/11/2026).

## Procesos

| Archivo | Cuándo corre | Qué hace |
|---|---|---|
| `diario.yml` | Todos los días a las 05:13 de Argentina (08:13 UTC), y a mano | Corre las pruebas, arma la edición del día con `python src/main.py --close`, la guarda en `docs/` y la sube a GitHub. Cloudflare Pages la publica en daily.lagrancrisis.com. Guarda los registros de la corrida (raw/ y logs/) por 30 días. |
| `probar-gemini.yml` | Solo a mano | Dice qué modelos de Gemini puede usar la clave y si responden hoy. No publica nada. |

Corrida a mano: pestaña **Actions** → elegir el proceso → **Run workflow**. En `diario.yml`, la casilla
**publicar** viene apagada: así se puede revisar una edición antes de subirla al sitio.

## Configuración en GitHub (Settings → Secrets and variables → Actions)

- Secreto `GEMINI_API_KEY`: la clave de Google AI Studio. Obligatorio.
- Variable `LGC_GEMINI_MODELS` (opcional): modelos en orden de preferencia, separados por coma.
  Si no existe, se usan `gemini-2.5-flash-lite,gemini-2.5-flash`.

## Diferencias con la PC

- No hay captura por hora: el cierre descarga las fuentes una sola vez. Medido con los datos de mayo
  de 2026: la captura por hora agregaba entre 4% y 16% de artículos, y eran los publicados entre las
  00:00 y las 05:00, que una descarga a las 05:13 también trae.
- Si una corrida falla, no se publica nada ese día y GitHub avisa por correo.
- Las tareas de Windows (`scripts/setup_local_tasks.ps1`, prefijo `LGC-`) quedan desactivadas para que
  no haya dos procesos armando la misma edición.

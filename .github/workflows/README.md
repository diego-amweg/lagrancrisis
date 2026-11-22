# Automatización del Diario

Desde noviembre de 2026 el Diario se arma y se publica solo desde GitHub, sin depender de la PC
(decisión del 21/11/2026).

## Procesos

| Archivo | Cuándo corre | Qué hace |
|---|---|---|
| `diario.yml` | Todos los días a las 05:13 de Argentina, con reintentos a las 07:13 y 10:13; también a mano | Corre las pruebas, arma la edición del día y la sube a GitHub; Cloudflare Pages la publica en daily.lagrancrisis.com. Los reintentos corren solo si la edición de hoy no se publicó. Los dos primeros intentos publican solo una edición completa; el último publica lo que haya. Guarda los registros 30 días. |
| `probar-gemini.yml` | Solo a mano | Dice si cada modelo de IA configurado responde hoy y qué modelos de Gemini ve la clave. No publica. |
| `atrasadas.yml` | Solo a mano | Modo `prueba`: arma 5 fechas viejas con Gemini y con Claude, sin publicar, y deja el informe comparativo y una revisión a ciegas en la rama `resultados-prueba`. Modo `reproceso`: arma y publica todas las ediciones atrasadas (15/05 al 21/11/2026) en orden, relanzándose solo hasta terminar. |

Corrida a mano: pestaña **Actions** → elegir el proceso → **Run workflow**.

## Modelos de IA

- Antes de procesar, el Diario pregunta a cada modelo si responde y usa primero los que responden.
- Si un modelo falla, pasa al siguiente aunque sea de otra empresa. Saturado (503): reintenta con
  espera. Sin cuota, sin acceso o sin clave: lo deja de lado por el resto de la corrida.
- Orden por defecto: `gemini-2.5-flash-lite`, `gemini-2.5-flash`, `claude-haiku-5-5`.
  Se cambia sin tocar código con la variable `LGC_MODELS`.
- Cada corrida registra tokens y costo aproximado por modelo (resumen de la corrida).

## Configuración en GitHub (Settings → Secrets and variables → Actions)

- Secretos: `GEMINI_API_KEY`, `ANTHROPIC_API_KEY` (alcanza con uno; con los dos hay respaldo entre
  empresas) e `INSUMOS_CLAVE` (abre las noticias guardadas de las atrasadas).
- Variable opcional: `LGC_MODELS`, modelos en orden de preferencia separados por coma.

## Diferencias con la PC

- No hay captura por hora: el cierre descarga las fuentes una sola vez. Medido con los datos de mayo
  de 2026: la captura por hora agregaba entre 4% y 16% de artículos, y eran los publicados entre las
  00:00 y las 05:00, que una descarga a las 05:13 también trae.
- Las tareas de Windows (`scripts/setup_local_tasks.ps1`, prefijo `LGC-`) se eliminan de la PC.

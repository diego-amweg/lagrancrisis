# Propuesta de Limpieza del Repositorio

Objetivo: reducir ruido operativo, bajar riesgo de confusiones y mejorar mantenibilidad sin romper la automatizacion actual.

## 1) Artefactos debug en raiz
Problema:
- Hay archivos debug_response*.txt en la raiz que contaminan el repo y mezclan corridas.

Propuesta:
- Mover todos los artefactos temporales a raw/YYYY-MM-DD/debug/.
- Mantener en raiz solo archivos fuente de proyecto.

Accion sugerida:
- Ajustar rutas de guardado en src/llm.py y src/main.py para usar carpeta diaria.

## 2) Ordenar documentacion interna
Problema:
- README mezcla estado historico y futuro, y no refleja exactamente la operacion local actual.

Propuesta:
- Mantener README como overview corto.
- Centralizar detalle operativo en docs/IMPLEMENTACION_Y_CAMBIOS.md.
- Agregar docs/OPERACION_DIARIA.md (runbook) en proxima iteracion.

## 3) Estandarizar carpeta docs/
Problema:
- docs/ cumple doble funcion: sitio publicado + docs internas.

Propuesta:
- Definir una convencion fija:
  - docs/YYYY/MM/DD y docs/static: publicacion web.
  - docs/*.md: documentacion interna.
- Alternativa (si prefieren separar): mover docs internas a repo_docs/.

## 4) Limpieza de scripts de prueba en src/
Problema:
- Existen scripts de test manual en src/ (test_gemini.py, test_gemini_minimal.py, test_deps.py) mezclados con codigo productivo.

Propuesta:
- Moverlos a carpeta tests_manual/ o scripts/dev/.
- Dejar src/ solo con modulos de pipeline.

## 5) Normalizar logs y retencion
Problema:
- logs/ puede crecer indefinidamente.

Propuesta:
- Politica de retencion simple (por ejemplo 30 dias) para logs de alto volumen.
- Mantener log de cierre diario y resumen semanal agregados.

## 6) Limpiar plantillas/config no usadas
Problema:
- workflow de GitHub Actions no esta activo en este repo local y la carpeta .github/workflows esta vacia.

Propuesta:
- Eliminar carpeta vacia o dejar un README corto aclarando que la automatizacion actual es Task Scheduler local.

## 7) Alinear ignore de artefactos temporales
Problema:
- Riesgo de versionar archivos transitorios.

Propuesta:
- Revisar .gitignore para incluir artefactos temporales adicionales de debug.

## Priorizacion recomendada
1. Alta: mover artefactos debug fuera de la raiz.
2. Alta: separar scripts de prueba de src/.
3. Media: orden documental (README + docs internas).
4. Media: politica de retencion de logs.
5. Baja: limpieza de carpetas vacias.

## Criterio de exito
- Raiz del repo sin artefactos transitorios.
- src/ solo con codigo de pipeline.
- Documentacion operativa unica y actualizada.
- Menor tiempo de onboarding y menor riesgo de errores de operacion.

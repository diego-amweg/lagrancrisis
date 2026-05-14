# Comparativo A/B - 2026-04-24

## Configuracion de variantes
- Variante A: orquestacion logica desactivada (flujo editorial clasico), Juez activado.
- Variante B: orquestacion logica activada (Redactor + Editor), Juez activado.

## Resultado ejecutivo
- Ganadora del dia: A
- Motivo principal: mejor score global del Juez y menor costo operativo por llamada LLM, con cero errores criticos en ambos casos.

## Tabla de metricas clave
| Metrica | A | B | Delta (B-A) |
|---|---:|---:|---:|
| downloaded | 138 | 149 | +11 |
| selected | 109 | 118 | +9 |
| published | 109 | 118 | +9 |
| coverage_ratio | 0.7899 | 0.7919 | +0.0020 |
| fallback_items_count | 18 | 24 | +6 |
| fallback_items_ratio | 0.1651 | 0.2034 | +0.0383 |
| translated_items_count | 27 | 36 | +9 |
| editorial_chunk_count | 7 | 7 | 0 |
| editorial_chunks_with_errors | 1 | 2 | +1 |
| editorial_autocorrect_runs | 1 | 1 | 0 |
| editor_agent_runs | 0 | 7 | +7 |
| editor_agent_failed_runs | 0 | 0 | 0 |
| llm_calls_total | 11 | 18 | +7 |
| llm_json_parse_failures_total | 16 | 18 | +2 |
| llm_model_fallback_activations | 1 | 0 | -1 |
| judge_quality_gate | PASS | PASS | = |
| judge_weighted_total | 100 | 96 | -4 |
| judge_critical_errors_count | 0 | 0 | 0 |

## Lectura editorial del Juez
- A: score perfecto 100, sin observaciones.
- B: score 96.5 (redondeado a 96 en metricas), con observaciones medias por snippets de evidencia truncados en multiples ids.

## Decision operativa del dia
1. Mantener A como variante de produccion para cierres diarios hasta nueva evidencia.
2. Mantener B en pruebas controladas A/B para mejorar calidad de evidencia en snippets y bajar fallback por item.
3. Repetir comparacion por 5 dias habiles para confirmar tendencia antes de promover B.

## Artefactos fuente
- A_pipeline_metrics.json
- B_pipeline_metrics.json
- A_judge_report.json
- B_judge_report.json

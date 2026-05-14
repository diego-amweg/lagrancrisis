# LEGAL_SOURCES

Fecha de corte: 2026-04-28
Jurisdiccion de referencia: Argentina (Ley 11.723 + terminos por fuente)

## Politica editorial obligatoria (aplicada en pipeline)
- Publicar solo redaccion propia.
- Microcita: prohibida.
- Atribucion obligatoria: fuente + enlace + fecha/hora por item.
- Imagenes: no usar imagenes de feeds privados sin licencia escrita.
- Exclusiones automaticas: Reuters, Bloomberg, Financial Times, WSJ.
- Revisión legal periodica: mensual (medios privados), trimestral (organismos oficiales).

## Matriz legal por fuente (condicion de uso aprobada)

| Fuente | Tipo | Condicion | Condicion de uso aprobada | Revision | Evidencia |
|---|---|---|---|---|---|
| BCRA | Oficial | allow | Uso informativo/editorial con redaccion propia, atribucion y enlace. Sin uso de logos como aval. | Trimestral | https://www.bcra.gob.ar/aviso-legal/ |
| INDEC | Oficial | allow | Datos y hechos con redaccion propia y atribucion. | Trimestral | https://www.indec.gob.ar/ |
| Boletin Oficial | Oficial | allow | Fuente primaria normativa con referencia oficial. | Trimestral | https://www.boletinoficial.gob.ar/estatica/institucional-mision |
| Casa Rosada | Oficial | allow | Comunicados oficiales con redaccion propia, atribucion y enlace. | Trimestral | https://www.casarosada.gob.ar/ |
| Ministerio de Economia (argentina.gob.ar) | Oficial | allow | Reutilizacion permitida con atribucion (CC BY 4.0 salvo excepciones). | Trimestral | https://www.argentina.gob.ar/terminos-y-condiciones |
| Federal Reserve | Oficial | conditional | Solo hechos y redaccion propia; revisar terminos en cada ciclo. | Trimestral | https://www.federalreserve.gov/feeds/feeds.htm |
| FMI | Oficial | conditional | Solo hechos y redaccion propia; revisar copyright/terms periodicamente. | Trimestral | https://www.imf.org/en/About/copyright-and-usage |
| Banco Central Europeo | Oficial | allow | Reutilizacion condicionada a citacion, exactitud e indicacion de cambios. | Trimestral | https://www.ecb.europa.eu/home/disclaimer/html/index.en.html |
| Ambito Financiero | Medio privado | conditional | No copiar texto sustancial; hechos con redaccion propia + atribucion. | Mensual | https://www.ambito.com/contenidos/aviso-legal.html |
| El Cronista | Medio privado | conditional | No reproducir contenido de suscripcion ni texto sustancial. | Mensual | https://www.cronista.com/ |
| La Nacion Economia | Medio privado | conditional | Derechos reservados; usar hechos con redaccion propia. | Mensual | https://www.contacto.lanacion.com.ar/tyc |
| Infobae Economia | Medio privado | conditional | Terminos restrictivos; solo hechos con redaccion propia. | Mensual | https://www.infobae.com/terminos-y-condiciones/ |
| Perfil Economia | Medio privado | conditional | Asumir derechos reservados hasta verificacion completa de terminos. | Mensual | https://www.perfil.com/ |
| Reuters Argentina | Medio privado | block | Bloqueada hasta licencia escrita formal. | Mensual | https://www.reuters.com/robots.txt |
| Reuters Economics | Medio privado | block | Bloqueada hasta licencia escrita formal. | Mensual | https://www.reuters.com/robots.txt |
| Bloomberg Linea | Medio privado | block | Bloqueada hasta licencia escrita formal. | Mensual | https://www.bloomberglinea.com/termsandconitions_en/ |
| Bloomberg Markets | Medio privado | block | Bloqueada hasta licencia escrita formal. | Mensual | https://www.bloomberg.com/notices/tos/ |
| Financial Times | Medio privado | block | Bloqueada hasta licencia escrita formal. | Mensual | https://help.ft.com/help/legal-privacy/terms-conditions/ |
| WSJ Markets | Medio privado | block | Bloqueada hasta licencia escrita formal. | Mensual | https://www.wsj.com/robots.txt |

## Implementacion tecnica de cumplimiento
- Matriz ejecutable: src/source_policy.json
- Opt-out dinamico sin redeploy: src/source_opt_out.json
- Enforcements en pipeline: src/main.py
  - bloqueo por condicion=block
  - exclusion por opt-out (names/urls/domains)
  - deshabilitacion de microcita
  - redaccion propia forzada ante solapamiento literal
  - atribucion obligatoria por item

## Procedimiento de opt-out (operativo)
1. Agregar la fuente solicitante a src/source_opt_out.json en names, urls o domains.
2. Ejecutar siguiente corrida (acumulado/cierre). No requiere cambios de codigo.
3. Confirmar en logs que aparece "Fuente excluida por opt-out dinamico".
4. Mantener evidencia de solicitud (ticket/email) en el sistema interno.

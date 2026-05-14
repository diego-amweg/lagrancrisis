import json, sys
sys.path.insert(0, 'src')
from fetch_rss import _detect_language

cases = [
    {'name': 'Ámbito Financiero',    'url': 'https://www.ambito.com/rss/economia.xml',      'category': 'macro_argentina'},
    {'name': 'El Cronista',          'url': 'https://www.cronista.com/files/rss/finanzas.xml','category': 'macro_argentina'},
    {'name': 'Infobae Economía',     'url': 'https://www.infobae.com/arc/outboundfeeds/rss', 'category': 'macro_argentina'},
    {'name': 'La Nación Economía',   'url': 'https://www.lanacion.com.ar/arc/outboundfeeds', 'category': 'macro_argentina'},
    {'name': 'Perfil Economía',      'url': 'https://www.perfil.com/feed/economia',          'category': 'politica_argentina'},
    {'name': 'BCRA',                 'url': 'https://www.argentina.gob.ar/rss.xml',          'category': 'macro_argentina'},
    {'name': 'Federal Reserve',      'url': 'https://www.federalreserve.gov/feeds/press_all.xml', 'category': 'internacional'},
    {'name': 'FMI',                  'url': 'https://www.imf.org/en/News/rss',               'category': 'internacional'},
    {'name': 'Reuters Economics',    'url': 'https://feeds.reuters.com/reuters/businessNews', 'category': 'internacional'},
]

print(f"{'Fuente':<25} {'Esperado':<10} {'Resultado':<10} {'Status'}")
print('-' * 60)
expected = ['es','es','es','es','es','es','en','en','en']
all_ok = True
for s, e in zip(cases, expected):
    r = _detect_language(s)
    ok = 'OK' if r == e else 'ERROR'
    if r != e:
        all_ok = False
    print(f"{s['name']:<25} {e:<10} {r:<10} {ok}")

print('\n' + '='*60)
if all_ok:
    print("✓ Todos los casos pasaron")
else:
    print("✗ Algunos casos fallaron")

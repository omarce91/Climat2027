"""
Met à jour les dates de consultation dans index.html.
Appelé par le workflow GitHub Actions après update_sources.py.
"""
import re, sys
from datetime import date

MONTHS = ['janvier','février','mars','avril','mai','juin',
          'juillet','août','septembre','octobre','novembre','décembre']

d = date.today()
date_fr = f'{d.day} {MONTHS[d.month-1]} {d.year}'

with open('index.html', encoding='utf-8') as f:
    html = f.read()

total = 0

html, n = re.subn(
    r'consultée? le \d+\s+[\w.]+\s+\d{4}',
    f'consulté le {date_fr}',
    html)
total += n
print(f'  pattern 1 (consulté le …)   : {n} remplacement(s)')

html, n = re.subn(
    r'Mise\s*à\s*jour\s*:\s*\d+\s+[\w.]+\s+\d{4}\.',
    f'Mise\u00a0à\u00a0jour\u00a0: {date_fr}.',
    html)
total += n
print(f'  pattern 2 (Mise à jour …)    : {n} remplacement(s)')

html, n = re.subn(
    r'mises à jour au \d+\s+[\w.]+\s+\d{4}',
    f'mises à jour au {date_fr}',
    html)
total += n
print(f'  pattern 3 (mises à jour au…) : {n} remplacement(s)')

if total == 0:
    print('⚠ AUCUN remplacement — vérifier les patterns ou le contenu de index.html')
    sys.exit(1)

with open('index.html', 'w', encoding='utf-8') as f:
    f.write(html)

print(f'✓ index.html : {total} dates mises à jour au {date_fr}')

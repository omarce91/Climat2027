"""
Met à jour les dates de consultation dans index.html.
Appelé par le workflow GitHub Actions après update_sources.py.
"""
import re
from datetime import date

MONTHS = ['janvier','février','mars','avril','mai','juin',
          'juillet','août','septembre','octobre','novembre','décembre']

d = date.today()
date_fr = f'{d.day} {MONTHS[d.month-1]} {d.year}'

with open('index.html', encoding='utf-8') as f:
    html = f.read()

# 1. Toutes les occurrences "consulté le X xxx XXXX" → aujourd'hui
html = re.sub(r'consulté le \d+\s+\w+\s+\d{4}', f'consulté le {date_fr}', html)

# 2. "Mise à jour : X xxx XXXX." → aujourd'hui
html = re.sub(r'Mise à jour\s*:\s*\d+\s+\w+\s+\d{4}\.', f'Mise à jour : {date_fr}.', html)

# 3. Commentaire JS "/* Données — mises à jour au X xxx XXXX */"
html = re.sub(r'mises à jour au \d+\s+\w+\s+\d{4}', f'mises à jour au {date_fr}', html)

with open('index.html', 'w', encoding='utf-8') as f:
    f.write(html)

print(f'✓ index.html : dates mises à jour au {date_fr}')

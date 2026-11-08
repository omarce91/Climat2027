"""
veille_candidats.py — Surveillance hebdomadaire #Climat2027
Détecte les nouveaux candidats déclarés non encore dans candidats.json.
Sources : Wikipedia API (liens article 2027) + votons-2027.fr (liste candidats).
Écrit veille.txt (committé hebdomadairement avec candidats.json).
Exécuté en PREMIER dans le workflow ; erreurs non-bloquantes (continue-on-error).
"""
import json, re, sys, urllib.request, urllib.error
from datetime import date

TODAY = date.today().isoformat()


def fetch(url, timeout=15):
    """Télécharge une URL ; retourne '' en cas d'échec (non-bloquant)."""
    try:
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'Climat2027-veille/1.0 (github.com/omarce91/Climat2027)'}
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode('utf-8', errors='replace')
    except Exception as e:
        print(f'  ⚠ fetch {url[:70]} → {e}')
        return ''


# ── 1. Charger les candidats connus ──────────────────────────────────────────
try:
    with open('candidats.json', encoding='utf-8') as f:
        cands = json.load(f)
    noms_connus = [c['nom'].lower() for c in cands]
    print(f'  candidats.json : {len(cands)} candidats connus')
except Exception as e:
    print(f'  ⚠ candidats.json : {e}')
    sys.exit(0)   # Pas de données → ne pas bloquer le workflow

rapport = [f'# Veille candidats — {TODAY}', '']

# ── 2. Wikipedia API ──────────────────────────────────────────────────────────
# Récupère tous les wikilinks de l'article sur l'élection présidentielle 2027.
# Les liens "Prénom Nom" (heuristique) qui ne sont pas dans candidats.json
# sont signalés comme potentiellement nouveaux.
print('  Wikipedia API...')
wiki_url = (
    'https://fr.wikipedia.org/w/api.php?action=parse'
    '&page=%C3%89lection_pr%C3%A9sidentielle_fran%C3%A7aise_de_2027'
    '&prop=links&format=json&redirects=1'
)
raw = fetch(wiki_url)
nouveaux_wiki = []
EXCL_WIKI = {
    'parti', 'france', 'rassemblement', 'insoumise', 'socialiste',
    'élection', 'primaire', 'liste', 'sondage', 'présidentielle',
    'programme', 'mouvement', 'républicain', 'démocrate', 'union',
    'europe', 'écologie', 'gauche', 'droite', 'centre', 'national',
}
if raw:
    try:
        data = json.loads(raw)
        for lk in data.get('parse', {}).get('links', []):
            if lk.get('ns') != 0:        # Espace de noms 0 = article principal
                continue
            titre = lk.get('*', '')
            # Heuristique : "Prénom Nom" (commence par majuscule + minuscule + espace + majuscule)
            if not re.match(r'^[A-ZÀ-Ü][a-zà-ü]+ [A-ZÀ-Ü]', titre):
                continue
            if any(x in titre.lower() for x in EXCL_WIKI):
                continue
            if titre.lower() not in noms_connus:
                nouveaux_wiki.append(titre)
    except Exception as e:
        print(f'  ⚠ parse Wikipedia JSON : {e}')

if nouveaux_wiki:
    rapport.append(f'## Wikipedia : {len(nouveaux_wiki)} noms non dans candidats.json')
    for n in nouveaux_wiki[:25]:
        rapport.append(f'- {n}')
    rapport.append('')
else:
    rapport.append('## Wikipedia : aucun nouveau nom détecté')
    rapport.append('')

# ── 3. votons-2027.fr ─────────────────────────────────────────────────────────
# Extrait les slugs de candidats depuis la page /candidats.
# Slugs non reconnus dans candidats.json = potentiellement nouveaux.
print('  votons-2027.fr...')
votons_html = fetch('https://votons-2027.fr/candidats')
nouveaux_votons = []
EXCL_VOTONS = {
    'programme', 'agenda', 'liste', 'themes', 'comparateur',
    'accueil', 'contact', 'mentions', 'candidats',
}
if votons_html:
    slugs = sorted(set(re.findall(r'/candidats/([a-z][a-z-]{3,})', votons_html)))
    for slug in slugs:
        if slug in EXCL_VOTONS:
            continue
        nom_mots = slug.replace('-', ' ').split()
        # Vérifier si un mot significatif (>4 lettres) du slug se retrouve dans un nom connu
        connu = any(
            any(mot in c['nom'].lower() for mot in nom_mots if len(mot) > 4)
            for c in cands
        )
        if not connu:
            nouveaux_votons.append(slug)

if nouveaux_votons:
    rapport.append(f'## votons-2027.fr : {len(nouveaux_votons)} slugs non reconnus')
    for s in nouveaux_votons[:25]:
        rapport.append(f'- https://votons-2027.fr/candidats/{s}')
    rapport.append('')
else:
    rapport.append('## votons-2027.fr : aucun nouveau candidat détecté')
    rapport.append('')

# ── 4. Résumé ─────────────────────────────────────────────────────────────────
nb = len(nouveaux_wiki) + len(nouveaux_votons)
if nb:
    rapport.append(f'**{nb} élément(s) à vérifier manuellement avant ajout à candidats.json.**')
else:
    rapport.append('✓ Aucun nouvel élément détecté.')
rapport.append('')

with open('veille.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(rapport))

print(f'✓ veille.txt écrit — {nb} élément(s) nouveau(x)')
if nouveaux_wiki:
    print('  Wikipedia  : ' + ', '.join(nouveaux_wiki[:5]) + ('…' if len(nouveaux_wiki) > 5 else ''))
if nouveaux_votons:
    print('  votons-2027: ' + ', '.join(nouveaux_votons[:5]) + ('…' if len(nouveaux_votons) > 5 else ''))

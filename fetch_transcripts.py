"""
fetch_transcripts.py — Récupère les transcripts d'émissions politiques #Climat2027
Sources : LCP (lcp.fr) + France Inter (franceinter.fr)
Dépose les nouveaux fichiers dans transcripts/ (format JSON).
Exécuté avant analyse_debats.py dans le workflow ; erreurs non-bloquantes.

Usage : python3 fetch_transcripts.py [--output transcripts/] [--max 10]
"""

import json, os, re, sys, time, urllib.request, urllib.error
from datetime import date, datetime, timedelta

# ── Config ────────────────────────────────────────────────────────────────────
OUTPUT_DIR  = "transcripts"
MAX_PAR_RUN = 10        # Nombre max de nouveaux fichiers par exécution
LOOKBACK    = 30        # Jours en arrière pour chercher des émissions
UA = "Climat2027-fetch/1.0 (github.com/omarce91/Climat2027; contact: o.marce91@gmail.com)"

# Noms de candidats/personnalités politiques à repérer dans les titres
# Format : slug (pour le nom de fichier) → liste de variantes à chercher
CANDIDATS = {
    "melenchon":    ["Mélenchon", "Melenchon"],
    "glucksmann":   ["Glucksmann"],
    "tondelier":    ["Tondelier"],
    "jadot":        ["Jadot"],
    "roussel":      ["Roussel"],
    "arthaud":      ["Arthaud"],
    "bardella":     ["Bardella"],
    "le-pen":       ["Le Pen", "Marine Le Pen"],
    "zemmour":      ["Zemmour"],
    "retailleau":   ["Retailleau"],
    "wauquiez":     ["Wauquiez"],
    "asselineau":   ["Asselineau"],
    "philippot":    ["Philippot"],
    "dupont-aignan":["Dupont-Aignan", "Dupont Aignan"],
}

# Mots-clés dans les titres signalant une émission politique exploitable
MOTS_POLITIQUE = [
    "politique", "présidentielle", "candidat", "programme",
    "élection", "campagne", "interview", "entretien", "invité",
]


# ── Utilitaires ───────────────────────────────────────────────────────────────

def fetch(url: str, timeout: int = 20) -> str:
    """GET HTTP ; retourne '' en cas d'erreur."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  ⚠ fetch {url[:80]} → {e}")
        return ""


def nettoyer(texte: str) -> str:
    """Supprime les balises HTML et normalise les espaces."""
    texte = re.sub(r"<[^>]+>", " ", texte)
    texte = re.sub(r"&nbsp;", " ", texte)
    texte = re.sub(r"&amp;", "&", texte)
    texte = re.sub(r"&[a-z]+;", "", texte)
    texte = re.sub(r"\s{2,}", " ", texte)
    return texte.strip()


def slug_fichier(source: str, slug_cand: str, date_str: str) -> str:
    """Génère le nom de fichier : YYYY-MM-DD_source_candidat.json"""
    return f"{date_str}_{source}_{slug_cand}.json"


def fichier_existe(nom: str) -> bool:
    return os.path.exists(os.path.join(OUTPUT_DIR, nom))


def sauvegarder(nom: str, data: dict) -> None:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    chemin = os.path.join(OUTPUT_DIR, nom)
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  ✓ {nom} ({len(data['texte'].split())} mots)")


def detecter_candidat(titre: str) -> tuple[str, str] | None:
    """Retourne (slug, nom_affiché) si un candidat est trouvé dans le titre."""
    for slug, variantes in CANDIDATS.items():
        for v in variantes:
            if v.lower() in titre.lower():
                return slug, v
    return None


def parser_date_fr(texte: str) -> str:
    """Extrait une date ISO depuis un texte HTML français."""
    # Format ISO direct
    m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", texte)
    if m:
        return m.group(1)
    # Format "publié le JJ mois AAAA"
    MOIS = {"janvier": "01", "février": "02", "mars": "03", "avril": "04",
            "mai": "05", "juin": "06", "juillet": "07", "août": "08",
            "septembre": "09", "octobre": "10", "novembre": "11", "décembre": "12"}
    m = re.search(r"(\d{1,2})\s+([a-zéû]+)\s+(\d{4})", texte, re.I)
    if m:
        mois = MOIS.get(m.group(2).lower())
        if mois:
            return f"{m.group(3)}-{mois}-{int(m.group(1)):02d}"
    return date.today().isoformat()


# ── Scraper LCP ───────────────────────────────────────────────────────────────

def scraper_lcp(max_items: int) -> list[dict]:
    """
    Cherche sur lcp.fr/actualites les interviews et débats récents
    mentionnant des candidats connus.
    """
    print("  LCP : recherche des transcripts...")
    nouveaux = []

    # Pages de résultats de recherche LCP (émissions / actualités politiques)
    urls_index = [
        "https://lcp.fr/emissions/invite-politique",
        "https://lcp.fr/emissions/questions-politiques",
        "https://lcp.fr/actualites/politique",
    ]

    liens_vus = set()

    for url_base in urls_index:
        if len(nouveaux) >= max_items:
            break
        html = fetch(url_base)
        if not html:
            continue

        # Extraire les liens d'articles/émissions
        liens = re.findall(r'href="(/(?:actualites|emissions)/[^"]{10,})"', html)
        for lien in liens:
            if lien in liens_vus:
                continue
            liens_vus.add(lien)

            url_art = "https://lcp.fr" + lien
            titre_m = re.search(r'<title[^>]*>([^<]+)</title>', html)

            # Chercher le candidat dans l'URL ou le titre de la liste
            cand = detecter_candidat(lien)
            if not cand:
                # Charge la page pour vérifier le titre
                html_art = fetch(url_art)
                if not html_art:
                    continue
                titre_m2 = re.search(r'<h1[^>]*>([^<]{10,})</h1>', html_art)
                titre = nettoyer(titre_m2.group(1)) if titre_m2 else ""
                cand = detecter_candidat(titre)
                if not cand:
                    continue
                html_page = html_art
            else:
                html_page = fetch(url_art)
                if not html_page:
                    continue

            slug_cand, nom_cand = cand

            # Extraire la date
            date_m = re.search(r'"datePublished"\s*:\s*"([^"]+)"', html_page)
            date_str = parser_date_fr(date_m.group(1) if date_m else "")

            # Vérifier la période
            try:
                if (date.today() - date.fromisoformat(date_str[:10])).days > LOOKBACK:
                    continue
            except Exception:
                pass

            # Vérifier que le fichier n'existe pas déjà
            nom = slug_fichier("lcp", slug_cand, date_str[:10])
            if fichier_existe(nom):
                continue

            # Extraire le texte de la transcription / article
            # LCP structure : <div class="field-items"> ou <div class="text-body">
            texte = ""
            for sel in [r'<div[^>]+class="[^"]*field[^"]*"[^>]*>(.*?)</div>',
                        r'<div[^>]+class="[^"]*content[^"]*"[^>]*>(.*?)</div>',
                        r'<article[^>]*>(.*?)</article>']:
                m = re.search(sel, html_page, re.S)
                if m:
                    texte = nettoyer(m.group(1))
                    if len(texte) > 300:
                        break

            if len(texte) < 200:
                # Fallback : tout le body sans nav/header/footer
                body = re.sub(r'<(?:nav|header|footer|script|style)[^>]*>.*?</(?:nav|header|footer|script|style)>', '', html_page, flags=re.S)
                texte = nettoyer(body)[:8000]

            if len(texte) < 100:
                continue

            # Titre de l'émission
            titre_em = ""
            h1 = re.search(r'<h1[^>]*>([^<]+)</h1>', html_page)
            if h1:
                titre_em = nettoyer(h1.group(1))

            nouveaux.append({
                "nom":      nom,
                "data": {
                    "date":     date_str[:10],
                    "emission": "LCP",
                    "titre":    titre_em,
                    "invite":   nom_cand,
                    "source":   url_art,
                    "texte":    texte,
                }
            })

            if len(nouveaux) >= max_items:
                break
        time.sleep(1)

    return nouveaux


# ── Scraper France Inter ──────────────────────────────────────────────────────

def scraper_france_inter(max_items: int) -> list[dict]:
    """
    Cherche sur franceinter.fr les grands entretiens et interviews récents
    mentionnant des candidats connus.
    """
    print("  France Inter : recherche des transcripts...")
    nouveaux = []

    urls_index = [
        "https://www.franceinter.fr/emissions/l-invite-de-8h20-le-grand-entretien",
        "https://www.franceinter.fr/emissions/questions-politiques",
        "https://www.franceinter.fr/politique",
    ]

    liens_vus = set()

    for url_base in urls_index:
        if len(nouveaux) >= max_items:
            break
        html = fetch(url_base)
        if not html:
            continue

        liens = re.findall(r'href="(https?://www\.franceinter\.fr/[^"]{20,})"', html)
        liens += ["https://www.franceinter.fr" + l
                  for l in re.findall(r'href="(/emissions/[^"]{15,})"', html)]

        for url_art in list(dict.fromkeys(liens)):  # dédoublonner
            if url_art in liens_vus:
                continue
            liens_vus.add(url_art)

            cand = detecter_candidat(url_art)
            if not cand:
                html_art = fetch(url_art)
                if not html_art:
                    continue
                h1 = re.search(r'<h1[^>]*>([^<]{10,})</h1>', html_art)
                titre = nettoyer(h1.group(1)) if h1 else ""
                cand = detecter_candidat(titre)
                if not cand:
                    # Chercher dans le chapeau / description
                    desc = re.search(r'<p[^>]+class="[^"]*intro[^"]*"[^>]*>([^<]{20,})</p>', html_art)
                    if desc:
                        cand = detecter_candidat(nettoyer(desc.group(1)))
                if not cand:
                    continue
                html_page = html_art
            else:
                html_page = fetch(url_art)
                if not html_page:
                    continue

            slug_cand, nom_cand = cand

            # Date
            date_m = re.search(r'"datePublished"\s*:\s*"([^"]+)"', html_page)
            if not date_m:
                date_m = re.search(r'<time[^>]+datetime="([^"]+)"', html_page)
            date_str = parser_date_fr(date_m.group(1) if date_m else "")

            try:
                if (date.today() - date.fromisoformat(date_str[:10])).days > LOOKBACK:
                    continue
            except Exception:
                pass

            nom = slug_fichier("france-inter", slug_cand, date_str[:10])
            if fichier_existe(nom):
                continue

            # Texte : France Inter met la transcription dans .content-wrapper ou .article-text
            texte = ""
            for sel in [
                r'<div[^>]+class="[^"]*content-wrapper[^"]*"[^>]*>(.*?)</div\s*>',
                r'<div[^>]+class="[^"]*article-text[^"]*"[^>]*>(.*?)</div\s*>',
                r'<div[^>]+class="[^"]*text-wrapper[^"]*"[^>]*>(.*?)</div\s*>',
            ]:
                m = re.search(sel, html_page, re.S)
                if m:
                    texte = nettoyer(m.group(1))
                    if len(texte) > 300:
                        break

            if len(texte) < 200:
                body = re.sub(r'<(?:nav|header|footer|script|style)[^>]*>.*?</(?:nav|header|footer|script|style)>', '', html_page, flags=re.S)
                texte = nettoyer(body)[:8000]

            if len(texte) < 100:
                continue

            h1 = re.search(r'<h1[^>]*>([^<]+)</h1>', html_page)
            titre_em = nettoyer(h1.group(1)) if h1 else ""

            nouveaux.append({
                "nom":  nom,
                "data": {
                    "date":     date_str[:10],
                    "emission": "France Inter",
                    "titre":    titre_em,
                    "invite":   nom_cand,
                    "source":   url_art,
                    "texte":    texte,
                }
            })

            if len(nouveaux) >= max_items:
                break
            time.sleep(1)

    return nouveaux


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Fetch transcripts LCP + France Inter")
    parser.add_argument("--output", default=OUTPUT_DIR,  help="Dossier de sortie")
    parser.add_argument("--max",    type=int, default=MAX_PAR_RUN, help="Max nouveaux fichiers")
    args = parser.parse_args()

    global OUTPUT_DIR
    OUTPUT_DIR = args.output
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"fetch_transcripts.py — {date.today().isoformat()}")
    print(f"  Dossier : {OUTPUT_DIR} | Max : {args.max} | Lookback : {LOOKBACK} j")

    total = 0
    erreurs = 0

    try:
        items_lcp = scraper_lcp(args.max)
        for item in items_lcp:
            try:
                sauvegarder(item["nom"], item["data"])
                total += 1
            except Exception as e:
                print(f"  ⚠ sauvegarde {item['nom']} : {e}")
                erreurs += 1
    except Exception as e:
        print(f"  ⚠ LCP scraper : {e}")

    try:
        items_fi = scraper_france_inter(max(0, args.max - total))
        for item in items_fi:
            try:
                sauvegarder(item["nom"], item["data"])
                total += 1
            except Exception as e:
                print(f"  ⚠ sauvegarde {item['nom']} : {e}")
                erreurs += 1
    except Exception as e:
        print(f"  ⚠ France Inter scraper : {e}")

    print(f"\n✓ fetch_transcripts : {total} nouveau(x) transcript(s) déposé(s) dans {OUTPUT_DIR}/")
    if erreurs:
        print(f"  ⚠ {erreurs} erreur(s) non-bloquante(s)")

    # Toujours exit 0 — ne pas bloquer le workflow
    sys.exit(0)


if __name__ == "__main__":
    main()

"""
analyse_debats.py — Comptage de mots-clés climat dans les transcripts #Climat2027
Input  : transcripts/*.txt  (texte brut)
         transcripts/*.json ({"date":…,"emission":…,"invite":…,"parti":…,"texte":…})
Output : debats_stats.json  +  post Bluesky (avec --post)
Usage  : python analyse_debats.py --input transcripts/ --output debats_stats.json
         python analyse_debats.py --demo  --output debats_stats.json
         python analyse_debats.py --input transcripts/ --output debats_stats.json --post
"""

import argparse, glob, json, os, re, sys
from datetime import date
from collections import defaultdict

# ── Mots-clés climat (regexes, insensible à la casse) ──────────────────────
KEYWORDS = {
    # Diagnostic
    "réchauffement climatique":  r"r[eé]chauffement\s+climatique",
    "changement climatique":     r"changement\s+climatique",
    "crise climatique":          r"crise\s+climatique",
    "urgence climatique":        r"urgence\s+climatique",
    "GIEC":                      r"\bGIEC\b",
    "accord de Paris":           r"accord\s+de\s+Paris",
    "COP":                       r"\bCOP\s*\d*",
    "CO2 / GES":                 r"\bCO2\b|\bGES\b|gaz\s+à\s+effet\s+de\s+serre|émissions\s+de\s+carbone",
    # Énergie
    "transition énergétique":    r"transition\s+[eé]nerg[eé]tique",
    "énergies renouvelables":    r"[eé]nergies?\s+renouvelables?|\bENR\b",
    "nucléaire":                 r"nucl[eé]aire",
    "éolien":                    r"[eé]olien",
    "solaire":                   r"solaire|photovolta[iï]que",
    "hydrogène":                 r"hydrog[eè]ne\s+vert",
    # Objectifs
    "neutralité carbone":        r"neutralit[eé]\s+carbone|z[eé]ro\s+carbone|net[\s-]z[eé]ro|bas\s+carbone",
    "planification écologique":  r"planification\s+[eé]cologique",
    "décarbonation":             r"d[eé]carbonat|d[eé]carbonisation",
    # Impacts / adaptation
    "inondation / sécheresse":   r"inondation|s[eé]cheresse|submersion",
    "canicule":                  r"canicule|vague\s+de\s+chaleur",
    "biodiversité":              r"biodiversit[eé]",
    "déforestation":             r"d[eé]forestation|artificialisation",
    # Secteurs
    "transport / mobilité":      r"v[eé]hicule\s+[eé]lectrique|mobilit[eé]\s+durable|avion|aviation",
    "agriculture / alimentation": r"agriculture\s+durable|agroécologie|alimentation\s+durable|élevage\s+intensif",
    "rénovation énergétique":    r"r[eé]novation\s+[eé]nerg[eé]tique|isolation\s+thermique|pass[eé]oire",
    # Finance
    "budget climat":             r"budget\s+[eé]cologique|financement\s+vert|obligation\s+verte|finance\s+climat",
    "taxe carbone":              r"taxe\s+carbone|prix\s+du\s+carbone|march[eé]\s+carbone",
}

# ── Mapping noms/slugs → sigle parti (pour nommage des fichiers) ───────────
PARTI_MAP = {
    # ÉELV
    "eelv": "ÉELV", "jadot": "ÉELV", "tondelier": "ÉELV",
    # Gauche écolo
    "gauche_eco": "G.Éco", "glucksmann": "Glucks.", "glucks": "Glucks.",
    # LFI
    "lfi": "LFI", "melenchon": "LFI", "mélenchon": "LFI",
    # PCF
    "pcf": "PCF", "roussel": "PCF",
    # LO
    "lo": "LO", "arthaud": "LO",
    # Horizons
    "horizons": "Hor.", "wauquiez": "Hor.", "macron": "Hor.",
    # Renaissance
    "renaissance": "Ren.",
    # LR
    "lr": "LR", "retailleau": "LR", "ciotti": "LR", "pécresse": "LR",
    # RN
    "rn": "RN", "le_pen": "RN", "le pen": "RN", "bardella": "RN",
    # Reconquête
    "reconquete": "Rec.", "reconquête": "Rec.", "zemmour": "Rec.",
    # DLF
    "dlf": "DLF", "dupont_aignan": "DLF",
    # Patriotes
    "patriotes": "Pat.", "philippot": "Pat.",
    # UPR
    "upr": "UPR", "asselineau": "UPR",
    # Debout
    "debout": "Deb.", "cheminade": "Deb.",
    # LFH
    "lfh": "LFH",
}


def detecter_parti(fichier: str, meta: dict) -> str:
    """Devine le parti depuis le nom de fichier ou les métadonnées."""
    if meta.get("parti"):
        return meta["parti"]
    slug = os.path.basename(fichier).lower().replace("-", "_").replace(" ", "_")
    slug = re.sub(r"\.(txt|json)$", "", slug)
    for cle, parti in PARTI_MAP.items():
        if cle in slug:
            return parti
    # Cherche dans le champ invite
    invite = meta.get("invite", "").lower()
    for cle, parti in PARTI_MAP.items():
        if cle in invite:
            return parti
    return "?"


def compter_keywords(texte: str) -> dict:
    """Retourne le nombre d'occurrences de chaque mot-clé dans le texte."""
    counts = {}
    for label, pattern in KEYWORDS.items():
        counts[label] = len(re.findall(pattern, texte, re.IGNORECASE))
    return counts


def lire_transcript(chemin: str) -> tuple[dict, str]:
    """Retourne (meta, texte) depuis un .txt ou .json."""
    ext = chemin.lower().rsplit(".", 1)[-1]
    if ext == "json":
        with open(chemin, encoding="utf-8") as f:
            data = json.load(f)
        texte = data.get("texte", "")
        meta = {k: v for k, v in data.items() if k != "texte"}
    else:
        with open(chemin, encoding="utf-8") as f:
            texte = f.read()
        # Essaie d'extraire date/émission/invité depuis le nom de fichier
        # format attendu : YYYY-MM-DD_emission_invite.txt
        base = os.path.basename(chemin).rsplit(".", 1)[0]
        parts = base.split("_", 2)
        meta = {}
        if len(parts) >= 1 and re.match(r"\d{4}-\d{2}-\d{2}", parts[0]):
            meta["date"] = parts[0]
        if len(parts) >= 2:
            meta["emission"] = parts[1].replace("-", " ")
        if len(parts) >= 3:
            meta["invite"] = parts[2].replace("-", " ")
    return meta, texte


def analyser_fichiers(dossier: str) -> list:
    """Analyse tous les .txt/.json dans le dossier."""
    resultats = []
    fichiers = sorted(
        glob.glob(os.path.join(dossier, "*.txt")) +
        glob.glob(os.path.join(dossier, "*.json"))
    )
    if not fichiers:
        print(f"  ⚠ Aucun transcript dans {dossier}")
        return resultats

    for chemin in fichiers:
        try:
            meta, texte = lire_transcript(chemin)
            if not texte.strip():
                print(f"  ⚠ {os.path.basename(chemin)} : texte vide, ignoré")
                continue
            kw = compter_keywords(texte)
            total = sum(kw.values())
            parti = detecter_parti(chemin, meta)
            res = {
                "fichier":        os.path.basename(chemin),
                "date":           meta.get("date", ""),
                "emission":       meta.get("emission", ""),
                "invite":         meta.get("invite", ""),
                "parti":          parti,
                "mots":           len(texte.split()),
                "total_mentions": total,
                "keywords":       {k: v for k, v in kw.items() if v > 0},
            }
            resultats.append(res)
            print(f"  ✓ {res['fichier']:<40} {total:>3} mention(s)  [{parti}]")
        except Exception as e:
            print(f"  ⚠ {os.path.basename(chemin)} : {e}")
    return resultats


def generer_demo() -> list:
    """Jeu de données de démonstration si aucun transcript disponible."""
    print("  Mode démo — données fictives pour test du workflow")
    demo = [
        {"fichier": "demo_lfi.txt",    "date": "2026-10-15", "emission": "Questions politiques",
         "invite": "Jean-Luc Mélenchon", "parti": "LFI",    "mots": 3200,
         "total_mentions": 42, "keywords": {"planification écologique": 12, "nucléaire": 8,
         "énergies renouvelables": 7, "CO2 / GES": 6, "transition énergétique": 5,
         "réchauffement climatique": 4}},
        {"fichier": "demo_eelv.txt",   "date": "2026-10-20", "emission": "Grand entretien",
         "invite": "Marine Tondelier",  "parti": "ÉELV",    "mots": 2800,
         "total_mentions": 61, "keywords": {"biodiversité": 14, "transition énergétique": 13,
         "accord de Paris": 9, "énergies renouvelables": 8, "nucléaire": 7,
         "réchauffement climatique": 6, "agriculture / alimentation": 4}},
        {"fichier": "demo_rn.txt",     "date": "2026-10-22", "emission": "L'Heure politique",
         "invite": "Jordan Bardella",   "parti": "RN",       "mots": 2500,
         "total_mentions": 7,  "keywords": {"nucléaire": 5, "CO2 / GES": 2}},
        {"fichier": "demo_lr.txt",     "date": "2026-10-28", "emission": "Questions politiques",
         "invite": "Bruno Retailleau",  "parti": "LR",       "mots": 2900,
         "total_mentions": 15, "keywords": {"nucléaire": 9, "transition énergétique": 3,
         "CO2 / GES": 2, "énergies renouvelables": 1}},
        {"fichier": "demo_glucks.txt", "date": "2026-11-02", "emission": "Grand entretien",
         "invite": "Raphaël Glucksmann","parti": "Glucks.",  "mots": 3100,
         "total_mentions": 38, "keywords": {"transition énergétique": 10, "CO2 / GES": 8,
         "accord de Paris": 7, "réchauffement climatique": 5, "taxe carbone": 4,
         "biodiversité": 4}},
    ]
    return demo


def agréger(resultats: list) -> dict:
    """Produit les totaux globaux et par parti."""
    total_global = sum(r["total_mentions"] for r in resultats)
    kw_global: dict = defaultdict(int)
    par_parti: dict = defaultdict(lambda: {"total": 0, "keywords": defaultdict(int)})

    for r in resultats:
        for k, v in r["keywords"].items():
            kw_global[k] += v
        parti = r["parti"]
        par_parti[parti]["total"] += r["total_mentions"]
        for k, v in r["keywords"].items():
            par_parti[parti]["keywords"][k] += v

    # Convertir defaultdicts en dicts triés
    kw_global_sorted = dict(sorted(kw_global.items(), key=lambda x: -x[1]))
    par_parti_clean = {}
    for p, d in sorted(par_parti.items(), key=lambda x: -x[1]["total"]):
        par_parti_clean[p] = {
            "total": d["total"],
            "keywords": dict(sorted(d["keywords"].items(), key=lambda x: -x[1])),
        }

    return {
        "generated":           date.today().isoformat(),
        "transcripts_analysés": len(resultats),
        "total_mentions":      total_global,
        "keywords_globaux":    kw_global_sorted,
        "par_parti":           par_parti_clean,
        "details":             sorted(resultats, key=lambda x: x["date"], reverse=True),
    }


# ── Post Bluesky ──────────────────────────────────────────────────────────────

def composer_post(stats: dict) -> str:
    """
    Compose un post Bluesky ≤ 300 caractères résumant les mentions climat.
    Exemple :
        📊 #Climat2027 — débats semaine du 3 nov. 2026
        Mentions « climat » par candidat·e :
        🟢 ÉELV 61 · LFI 42 · Glucks. 38
        🔴 LR 15 · RN 7
        Top : transition énergétique (31), nucléaire (29)
        #Climat #Presidentielle2027
    """
    MOIS = ['janvier','février','mars','avril','mai','juin',
            'juillet','août','septembre','octobre','novembre','décembre']
    d = date.today()
    date_fr = f"{d.day} {MOIS[d.month-1]} {d.year}"

    nb_t = stats["transcripts_analysés"]
    # Si démo, l'indiquer
    is_demo = all(r["fichier"].startswith("demo_") for r in stats["details"])
    source_label = f"{nb_t} émission{'s' if nb_t > 1 else ''} analysée{'s' if nb_t > 1 else ''}"
    if is_demo:
        source_label = "données de démonstration"

    # Partis triés par mentions décroissantes
    par_parti = stats["par_parti"]   # déjà trié
    top_partis = list(par_parti.items())   # [(parti, {total, keywords}), …]

    # Seuil arbitraire : 20+ mentions = "engagé", <10 = "faible"
    engages  = [(p, d["total"]) for p, d in top_partis if d["total"] >= 20]
    faibles  = [(p, d["total"]) for p, d in top_partis if d["total"] <  10]
    moyens   = [(p, d["total"]) for p, d in top_partis
                if 10 <= d["total"] < 20]

    def fmt_liste(lst):
        return " · ".join(f"{p} {n}" for p, n in lst[:5])

    lignes_partis = []
    if engages:
        lignes_partis.append("🟢 " + fmt_liste(engages))
    if moyens:
        lignes_partis.append("🟡 " + fmt_liste(moyens))
    if faibles:
        lignes_partis.append("🔴 " + fmt_liste(faibles))

    # Top 2 mots-clés globaux
    top_kw = list(stats["keywords_globaux"].items())[:2]
    top_kw_str = ", ".join(f"{k} ({v})" for k, v in top_kw)

    lignes = [
        f"📊 #Climat2027 — semaine du {date_fr}",
        f"Mentions « Climat » dans {source_label} :",
    ] + lignes_partis + [
        f"Top : {top_kw_str}",
        "#Climat #Presidentielle2027",
    ]

    post = "\n".join(lignes)

    # Tronquer si > 300 caractères (limite Bluesky)
    if len(post) > 295:
        # Supprimer la ligne "moyens" si présente
        lignes2 = [l for l in lignes if not l.startswith("🟡")]
        post = "\n".join(lignes2)
    if len(post) > 295:
        # Raccourcir la ligne Top
        lignes3 = [l for l in lignes if not l.startswith("Top")]
        post = "\n".join(lignes3)
    if len(post) > 295:
        post = post[:292] + "…"

    return post


def poster_bluesky(post: str) -> bool:
    """Poste sur Bluesky via atproto ; retourne True si succès."""
    try:
        from atproto import Client
    except ImportError:
        print("  ⚠ atproto non installé — pip install atproto")
        return False

    try:
        with open("credentials.json", encoding="utf-8") as f:
            creds = json.load(f)
        handle   = creds["handle_c27"]
        password = creds["app_password_c27"]
    except Exception as e:
        print(f"  ⚠ credentials.json : {e}")
        return False

    try:
        client = Client()
        client.login(handle, password)
        client.send_post(text=post)
        print(f"  ✓ Post Bluesky envoyé ({len(post)} caractères)")
        return True
    except Exception as e:
        print(f"  ⚠ Post Bluesky échoué : {e}")
        return False


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Analyse mots-clés climat dans les transcripts")
    parser.add_argument("--input",  default="transcripts/", help="Dossier des transcripts")
    parser.add_argument("--output", default="debats_stats.json", help="Fichier de sortie")
    parser.add_argument("--demo",   action="store_true", help="Mode démo (données fictives)")
    parser.add_argument("--post",   action="store_true", help="Poster le résumé sur Bluesky")
    args = parser.parse_args()

    print(f"analyse_debats.py — {date.today().isoformat()}")

    if args.demo:
        resultats = generer_demo()
    else:
        if not os.path.isdir(args.input):
            print(f"  ⚠ Dossier {args.input} introuvable — mode démo activé")
            resultats = generer_demo()
        else:
            resultats = analyser_fichiers(args.input)
            if not resultats:
                print("  Aucun transcript analysable — mode démo activé")
                resultats = generer_demo()

    stats = agréger(resultats)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    print(f"\n✓ {args.output} : {stats['transcripts_analysés']} transcript(s), "
          f"{stats['total_mentions']} mention(s) climat au total")

    # Résumé console
    print("\nTop 5 mots-clés :")
    for kw, n in list(stats["keywords_globaux"].items())[:5]:
        print(f"  {kw:<35} {n:>4}")
    print("\nMentions par parti :")
    for parti, d in stats["par_parti"].items():
        print(f"  {parti:<12} {d['total']:>4}")

    # Post Bluesky
    if args.post:
        post = composer_post(stats)
        print(f"\nPost Bluesky ({len(post)} car.) :\n{post}\n")
        poster_bluesky(post)


if __name__ == "__main__":
    main()

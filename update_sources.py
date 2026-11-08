#!/usr/bin/env python3
"""
Consulte les sources configurées dans sources.json, analyse les changements
de positions des candidats sur le climat avec Mistral, et met à jour :
  - sources.json  → last_consulted (date du jour)
  - candidats.json → scores si Mistral détecte un changement significatif
  - CHANGES.md     → compte-rendu des modifications détectées (si changements)

Doit être lancé AVANT generate_og.py dans le workflow GitHub Actions.

Usage :
    python update_sources.py
    python update_sources.py --dry-run          # affiche sans modifier
    python update_sources.py --config cred.json
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

SOURCES_FILE   = Path("sources.json")
CANDIDATS_FILE = Path("candidats.json")
CHANGES_FILE   = Path("CHANGES.md")

USER_AGENT = (
    "Mozilla/5.0 (compatible; Climat2027Bot/1.0; "
    "+https://climat2027.fr)"
)
FETCH_TIMEOUT = 15   # secondes
MAX_CHARS     = 8000  # caractères de texte extraits par source


# ── Credentials ───────────────────────────────────────────────────────────────

def load_mistral_key(config_path: Path) -> str | None:
    key = os.environ.get("MISTRAL_API_KEY", "")
    if not key and config_path.exists():
        try:
            data = json.loads(config_path.read_text())
            key = data.get("mistral_api_key", "")
        except Exception:
            pass
    return key or None


# ── Lecture / écriture JSON ───────────────────────────────────────────────────

def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Fetching des pages ────────────────────────────────────────────────────────

def fetch_text(url: str) -> str | None:
    """Télécharge une URL et retourne le texte brut (balises HTML supprimées)."""
    try:
        req = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            raw = resp.read(500_000).decode("utf-8", errors="replace")
    except (URLError, HTTPError, Exception) as e:
        print(f"  ⚠ Impossible de charger {url} : {e}")
        return None

    # Supprime les balises HTML et normalise les espaces
    text = re.sub(r"<style[^>]*>.*?</style>", " ", raw, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&[a-zA-Z]+;", " ", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text[:MAX_CHARS]


def fetch_all_sources(sources: list[dict]) -> dict[str, str]:
    """Retourne {nom_source: texte_extrait} pour chaque source active."""
    results = {}
    for src in sources:
        if not src.get("active"):
            continue
        name = src["name"]
        url  = src["url"]
        print(f"  → {name} ({url})")
        text = fetch_text(url)
        if text:
            results[name] = text
            print(f"     {len(text)} caractères extraits.")
        time.sleep(1)   # politesse
    return results


# ── Analyse Mistral ───────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Tu es un expert en politique environnementale française.
Tu analyses les programmes des candidats à l'élection présidentielle française 2027
sous l'angle du climat : atténuation (réduction des émissions) et adaptation.

Chaque candidat est noté sur deux axes de 0 à 10 :
- att (atténuation) : ambition de réduction des émissions de CO₂
- adp (adaptation) : ambition d'adaptation au changement climatique
- b (intentions de vote actuelles en %)

Réponds UNIQUEMENT en JSON valide, sans explication.
"""

def mistral_analyze(source_texts: dict[str, str],
                    candidats: list[dict],
                    mistral_key: str) -> dict:
    """
    Envoie les textes sources + scores actuels à Mistral.
    Retourne {"changes": [...], "new_sources": [...], "summary": "..."}.
    """
    try:
        from mistralai import Mistral
    except ImportError:
        print("[erreur] mistralai non installé — pip install mistralai")
        return

    # Résumé des scores actuels
    scores_txt = "\n".join(
        f"  {c['s']}: att={c['att']}, adp={c['adp']}, b={c['b']}"
        for c in candidats
    )

    # Extraits des sources (limités pour tenir dans le contexte)
    excerpts = ""
    for name, text in source_texts.items():
        excerpts += f"\n\n=== {name} ===\n{text[:3000]}"

    user_msg = f"""Scores actuels des candidats (au {date.today().isoformat()}) :
{scores_txt}

Voici les extraits des sources consultées aujourd'hui :{excerpts}

---

En te basant sur ces informations :
1. Les scores att/adp/b de certains candidats doivent-ils être mis à jour ?
2. Y a-t-il de nouveaux candidats déclarés absents de la liste ?
3. Résume en 2-3 phrases ce que tu as trouvé de notable.

Réponds en JSON avec cette structure exacte :
{{
  "changes": [
    {{"s": "NomCandidat", "att": 7.5, "adp": 6.0, "b": 15.0, "reason": "raison courte"}}
  ],
  "new_candidates": [
    {{"s": "NomCourt", "att": 5.0, "adp": 4.0, "b": 1.0, "mk": "h", "c": "#aaaaaa", "reason": "raison"}}
  ],
  "new_sources": [
    {{"name": "Nom", "url": "https://...", "description": "..."}}
  ],
  "summary": "Résumé en 2-3 phrases de ce qui a changé."
}}

Si rien n'a changé, retourne des listes vides et un summary "Aucun changement significatif détecté."
"""

    client   = Mistral(api_key=mistral_key)
    response = client.chat.complete(
        model    = "mistral-large-latest",
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_msg},
        ],
        temperature = 0.1,
    )

    raw = response.choices[0].message.content.strip()

    # Extrait le JSON de la réponse (robuste au markdown)
    json_match = re.search(r"\{[\s\S]+\}", raw)
    if not json_match:
        raise ValueError(f"Réponse Mistral non parseable : {raw[:200]}")

    return json.loads(json_match.group())


# ── Application des changements ───────────────────────────────────────────────

def apply_changes(candidats: list[dict], analysis: dict) -> tuple[list[dict], list[str]]:
    """
    Applique les changements suggérés par Mistral.
    Retourne (candidats_mis_à_jour, lignes_journal).
    """
    journal = []
    updated = {c["s"]: c for c in candidats}

    for change in analysis.get("changes", []):
        s = change["s"]
        if s in updated:
            old = updated[s].copy()
            for field in ("att", "adp", "b"):
                if field in change:
                    updated[s][field] = round(float(change[field]), 1)
            reason = change.get("reason", "")
            diff = {f: (old[f], updated[s][f])
                    for f in ("att", "adp", "b") if old[f] != updated[s][f]}
            if diff:
                parts = ", ".join(f"{f}: {a}→{b}" for f, (a, b) in diff.items())
                journal.append(f"- **{s}** : {parts} — {reason}")

    for new_c in analysis.get("new_candidates", []):
        s = new_c.get("s", "")
        if s and s not in updated:
            updated[s] = {
                "s":  s,
                "att": round(float(new_c.get("att", 5.0)), 1),
                "adp": round(float(new_c.get("adp", 5.0)), 1),
                "b":   round(float(new_c.get("b",   1.0)), 1),
                "mk":  new_c.get("mk", "h"),
                "c":   new_c.get("c", "#aaaaaa"),
            }
            reason = new_c.get("reason", "")
            journal.append(f"- **{s}** (nouveau) : att={updated[s]['att']}, "
                           f"adp={updated[s]['adp']}, b={updated[s]['b']} — {reason}")

    # Préserve l'ordre original + nouveaux en fin
    original_keys = [c["s"] for c in candidats]
    result = [updated[k] for k in original_keys if k in updated]
    for k, v in updated.items():
        if k not in original_keys:
            result.append(v)

    return result, journal


def apply_new_sources(sources_data: dict, analysis: dict) -> list[str]:
    """Ajoute les nouvelles sources détectées. Retourne le journal."""
    journal = []
    existing_urls = {s["url"] for s in sources_data.get("sources", [])}

    for new_s in analysis.get("new_sources", []):
        url = new_s.get("url", "")
        if url and url not in existing_urls:
            sources_data["sources"].append({
                "name":        new_s.get("name", url),
                "url":         url,
                "description": new_s.get("description", ""),
                "theme_climate": "climat",
                "active": True,
            })
            existing_urls.add(url)
            journal.append(f"- Nouvelle source ajoutée : **{new_s.get('name', url)}** ({url})")

    return journal


def write_changes_md(candidat_journal: list[str],
                     source_journal: list[str],
                     summary: str,
                     consulted_date: str) -> None:
    lines = [
        f"# Changements détectés le {consulted_date}\n",
        f"{summary}\n",
    ]
    if candidat_journal:
        lines += ["\n## Candidats mis à jour\n"] + candidat_journal
    if source_journal:
        lines += ["\n## Nouvelles sources\n"] + source_journal

    # Préfixe la nouvelle entrée au fichier existant
    existing = CHANGES_FILE.read_text(encoding="utf-8") if CHANGES_FILE.exists() else ""
    CHANGES_FILE.write_text(
        "\n".join(lines) + "\n\n---\n\n" + existing,
        encoding="utf-8"
    )


# ── Point d'entrée ────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Consulte les sources et met à jour candidats.json + sources.json."
    )
    parser.add_argument("--config",  default="credentials.json")
    parser.add_argument("--dry-run", action="store_true",
                        help="Affiche sans modifier les fichiers")
    args = parser.parse_args()

    # ── Chargement ────────────────────────────────────────────────────────────
    if not SOURCES_FILE.exists():
        print(f"[avertissement] {SOURCES_FILE} introuvable — consultation ignorée.")
        return
    if not CANDIDATS_FILE.exists():
        print(f"[avertissement] {CANDIDATS_FILE} introuvable — consultation ignorée.")
        return

    sources_data  = load_json(SOURCES_FILE)
    candidats_data = load_json(CANDIDATS_FILE)
    candidats     = candidats_data["candidats"]
    mistral_key   = load_mistral_key(Path(args.config))

    today_iso  = date.today().isoformat()
    today_fr   = date.today().strftime("%-d %B %Y") if sys.platform != "win32" \
                 else date.today().strftime("%d %B %Y").lstrip("0")

    print(f"=== update_sources.py — {today_fr} ===")
    print(f"Consultation de {len([s for s in sources_data['sources'] if s.get('active')])} sources…")

    # ── Fetching ──────────────────────────────────────────────────────────────
    source_texts = fetch_all_sources(sources_data["sources"])

    if not source_texts:
        print("Aucune source chargée. Mise à jour de la date de consultation uniquement.")
        if not args.dry_run:
            sources_data["last_consulted"] = today_iso
            save_json(SOURCES_FILE, sources_data)
        return

    # ── Analyse Mistral ───────────────────────────────────────────────────────
    if not mistral_key:
        print("[avertissement] Clé Mistral absente — analyse sautée, date mise à jour.")
        if not args.dry_run:
            sources_data["last_consulted"] = today_iso
            save_json(SOURCES_FILE, sources_data)
        return

    print("Analyse des changements avec Mistral…")
    try:
        analysis = mistral_analyze(source_texts, candidats, mistral_key)
    except Exception as e:
        print(f"[erreur Mistral] {e}")
        if not args.dry_run:
            sources_data["last_consulted"] = today_iso
            save_json(SOURCES_FILE, sources_data)
        return

    summary          = analysis.get("summary", "")
    candidat_journal = []
    source_journal   = []

    print(f"\nRésumé Mistral : {summary}")

    # ── Application des changements ───────────────────────────────────────────
    new_candidats, candidat_journal = apply_changes(candidats, analysis)
    if candidat_journal:
        print(f"\n{len(candidat_journal)} mise(s) à jour candidat(s) :")
        for line in candidat_journal:
            print(f"  {line}")
    else:
        print("Aucun changement de score candidat.")

    source_journal = apply_new_sources(sources_data, analysis)
    if source_journal:
        print(f"\n{len(source_journal)} nouvelle(s) source(s) :")
        for line in source_journal:
            print(f"  {line}")

    # ── Sauvegarde ────────────────────────────────────────────────────────────
    if args.dry_run:
        print("\n[dry-run] Aucune modification écrite.")
        return

    # Mise à jour candidats.json
    candidats_data["candidats"]     = new_candidats
    candidats_data["last_consulted"] = today_iso
    if candidat_journal:
        candidats_data["last_updated"] = today_iso
        # Mémorise les changements dans les notes
        note = f"{today_fr} : " + "; ".join(
            line.lstrip("- ").split(" — ")[0] for line in candidat_journal
        )
        candidats_data.setdefault("notes", []).append(note)
    save_json(CANDIDATS_FILE, candidats_data)

    # Mise à jour sources.json
    sources_data["last_consulted"] = today_iso
    save_json(SOURCES_FILE, sources_data)

    # Journal des changements
    has_changes = bool(candidat_journal or source_journal)
    if has_changes:
        write_changes_md(candidat_journal, source_journal, summary, today_fr)
        print(f"\n✓ Changements consignés dans {CHANGES_FILE}")

    print(f"\n✓ sources.json + candidats.json mis à jour (consulté le {today_fr})")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Rétro-remplit markers.json avec toutes les communes des posts déjà
envoyés (indices 0 à next_index - 1 dans state.json).

Utile pour initialiser la carte quand le script a déjà tourné
plusieurs jours sans que markers.json ait été alimenté, ou pour
reconstituer markers.json après une perte.

Usage :
    python backfill_markers.py                  # lit posts.md + state.json
    python backfill_markers.py --all            # géocode TOUS les posts (pas seulement les envoyés)
    python backfill_markers.py --dry-run        # affiche sans écrire
"""

import argparse
import json
import re
import sys
import time
import unicodedata
import urllib.request
from pathlib import Path
from urllib.parse import quote_plus


def load_commune_posts(posts_file: Path) -> list[str]:
    content = posts_file.read_text(encoding="utf-8")
    blocks  = re.split(r"\n-{3,}\n", content)
    return [b.strip() for b in blocks if b.strip().startswith("#1Jour1CommuneSinistree")]


def load_state(state_file: Path) -> dict:
    if state_file.exists():
        return json.loads(state_file.read_text(encoding="utf-8"))
    return {"next_index": 0, "posted_log": []}


def load_markers(markers_file: Path) -> list[dict]:
    if markers_file.exists():
        return json.loads(markers_file.read_text(encoding="utf-8"))
    return []


def save_markers(markers_file: Path, markers: list[dict]) -> None:
    markers_file.write_text(
        json.dumps(markers, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def parse_fields(post_text: str) -> dict | None:
    lines = post_text.splitlines()
    if len(lines) < 3:
        return None
    parts = [p.strip() for p in lines[1].split(",")]
    if len(parts) < 3:
        return None
    commune, departement, type_ = parts[0], parts[1], ",".join(parts[2:]).strip()
    m = re.search(r"#Jour(\d+)", post_text)
    return {"commune": commune, "departement": departement,
            "type": type_, "day": int(m.group(1)) if m else None}


def normalize(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def geocode(commune: str, departement: str) -> tuple[float, float] | None:
    url = (
        f"https://geo.api.gouv.fr/communes?nom={quote_plus(commune)}"
        "&fields=centre,departement&boost=population&limit=5"
    )
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            results = json.loads(r.read())
    except Exception as e:
        print(f"    [erreur réseau] {e}")
        return None
    target = normalize(departement)
    for r in results:
        if normalize(r.get("departement", {}).get("nom", "")) == target:
            c = r.get("centre", {}).get("coordinates")
            if c and len(c) == 2:
                return c[1], c[0]
    if results:
        c = results[0].get("centre", {}).get("coordinates")
        if c and len(c) == 2:
            return c[1], c[0]
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Rétro-remplit markers.json avec les communes déjà postées."
    )
    parser.add_argument("--posts-file",   default="posts.md")
    parser.add_argument("--state-file",   default="state.json")
    parser.add_argument("--markers-file", default="markers.json")
    parser.add_argument("--all", action="store_true",
                        help="Géocode tous les posts, pas seulement les déjà envoyés")
    parser.add_argument("--dry-run", action="store_true",
                        help="Affiche sans modifier markers.json")
    parser.add_argument("--delay", type=float, default=0.2,
                        help="Pause entre chaque requête de géocodage en secondes (défaut: 0.2)")
    args = parser.parse_args()

    posts_file   = Path(args.posts_file)
    state_file   = Path(args.state_file)
    markers_file = Path(args.markers_file)

    if not posts_file.exists():
        sys.exit(f"Fichier introuvable : {posts_file}")

    posts = load_commune_posts(posts_file)
    if not posts:
        sys.exit(f"Aucun post trouvé dans {posts_file}.")

    state      = load_state(state_file)
    next_index = state.get("next_index", 0)
    posted_log = {e["index"]: e.get("date") for e in state.get("posted_log", [])}

    # Détermine les posts à traiter
    if args.all:
        to_process = list(range(len(posts)))
        print(f"Mode --all : {len(to_process)} posts à géocoder.")
    else:
        to_process = list(range(next_index))
        print(f"{next_index} post(s) déjà envoyé(s) à géocoder (state.json).")

    if not to_process:
        print("Rien à faire.")
        return

    # Charge les marqueurs existants pour ne pas dupliquer
    existing = load_markers(markers_file)
    existing_communes = {(m["commune"], m["departement"]) for m in existing}
    print(f"{len(existing)} marqueur(s) déjà dans markers.json.")

    new_markers = []
    ok = skip = fail = 0

    for idx in to_process:
        post = posts[idx]
        fields = parse_fields(post)
        if not fields:
            print(f"  [{idx+1}] Impossible d'analyser le post — ignoré.")
            fail += 1
            continue

        commune    = fields["commune"]
        departement = fields["departement"]
        key        = (commune, departement)

        if key in existing_communes:
            print(f"  [{idx+1}] {commune} ({departement}) — déjà dans markers.json, ignoré.")
            skip += 1
            continue

        print(f"  [{idx+1}/{len(to_process)}] Géocodage de {commune} ({departement})...", end=" ")
        coords = geocode(commune, departement)

        if coords:
            lat, lon = coords
            date_str = posted_log.get(idx, "")
            new_markers.append({
                **fields,
                "date": date_str,
                "lat":  lat,
                "lon":  lon,
            })
            existing_communes.add(key)
            print(f"✓ {lat:.5f}, {lon:.5f}")
            ok += 1
        else:
            print("✗ échec.")
            fail += 1

        if args.delay > 0:
            time.sleep(args.delay)

    print()
    print(f"Résultat : {ok} géocodé(s), {skip} ignoré(s) (doublon), {fail} échoué(s).")

    if args.dry_run:
        print(f"[dry-run] markers.json non modifié ({len(new_markers)} nouveau(x) marqueur(s) auraient été ajoutés).")
        return

    if new_markers:
        all_markers = existing + new_markers
        save_markers(markers_file, all_markers)
        print(f"markers.json mis à jour : {len(all_markers)} marqueur(s) au total.")
    else:
        print("Aucun nouveau marqueur ajouté.")


if __name__ == "__main__":
    main()

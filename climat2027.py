#!/usr/bin/env python3
"""
Script central de la campagne #Climat2027.

Trois modes au choix :

  --mode commune (PAR DÉFAUT sans argument)
      Poste le PROCHAIN post #1Jour1CommuneSinistree de posts.md.
      Limite stricte : 1 post par jour maximum.
      Géocode la commune en arrière-plan et met à jour markers.json
      pour la carte cumulative.

  --mode post
      Poste un message d'engagement #Climat2027 tiré au hasard dans
      humor_posts.md (+ slogan.txt avec fréquence réelle ~1/3).
      Pondéré par le succès passé (likes + reposts).

  --mode reply
      Répond aux posts likés par le compte dans les --hours dernières
      heures (défaut 24h) qui n'ont pas encore de réponse du compte,
      avec un message tiré de la même liste pondérée.
      Pause --delay secondes entre chaque envoi (défaut 5s).

----------------------------------------------------------------------
Pré-requis
----------------------------------------------------------------------
    pip install atproto

credentials.json (ne jamais commiter ce fichier) :
    {
        "handle": "climat2027.bsky.social",
        "app_password": "xxxx-xxxx-xxxx-xxxx"
    }

----------------------------------------------------------------------
Usage
----------------------------------------------------------------------
    python climat2027.py                           # → mode commune
    python climat2027.py --dry-run                 # → mode commune, test
    python climat2027.py --force                   # → mode commune, force
    python climat2027.py --mode post               # → message standalone
    python climat2027.py --mode reply              # → réponses aux likes
    python climat2027.py --stats-only              # → classement sans poster
"""

import argparse
import io
import json
import random
import re
import sys
import time
import unicodedata
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote_plus

MAX_POST_LENGTH      = 300
SLOGAN_PROBABILITY   = 1 / 2   # → fréquence réelle ~1/3 (voir pick_message)
DEFAULT_DELAY        = 5
BASE_WEIGHT          = 3       # poids plancher pour les messages sans score


# ─────────────────────────────────────────────────────────────────────
# Authentification (commun à tous les modes)
# ─────────────────────────────────────────────────────────────────────

def load_credentials(config_file: Path) -> tuple[str, str, str | None]:
    if not config_file.exists():
        sys.exit(
            f"Fichier d'identifiants introuvable : {config_file}\n"
            '{\n  "handle": "ton-compte.bsky.social",\n'
            '  "app_password": "xxxx-xxxx-xxxx-xxxx"\n}'
        )
    try:
        data = json.loads(config_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"Fichier d'identifiants invalide : {e}")
    handle = data.get("handle")
    app_password = data.get("app_password")
    if not handle or not app_password:
        sys.exit("credentials.json doit contenir 'handle' et 'app_password'.")
    map_url = data.get("map_url") or None
    return handle, app_password, map_url


def build_richtext(client_utils, text: str):
    """Hashtags et liens cliquables sur Bluesky."""
    builder = client_utils.TextBuilder()
    for tok in re.split(r"(#\w+|https?://\S+)", text):
        if not tok:
            continue
        if tok.startswith("#"):
            builder.tag(tok, tok[1:])
        elif tok.startswith("http"):
            builder.link(tok, tok)
        else:
            builder.text(tok)
    return builder


# ─────────────────────────────────────────────────────────────────────
# Mode COMMUNE — #1Jour1CommuneSinistree
# ─────────────────────────────────────────────────────────────────────

def _load_commune_posts(posts_file: Path) -> list[str]:
    content = posts_file.read_text(encoding="utf-8")
    blocks = re.split(r"\n-{3,}\n", content)
    return [b.strip() for b in blocks if b.strip().startswith("#1Jour1CommuneSinistree")]


def _load_commune_state(state_file: Path) -> dict:
    if state_file.exists():
        return json.loads(state_file.read_text(encoding="utf-8"))
    return {"next_index": 0, "last_posted_date": None, "posted_log": []}


def _save_commune_state(state_file: Path, state: dict) -> None:
    state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_markers(markers_file: Path) -> list[dict]:
    if markers_file.exists():
        return json.loads(markers_file.read_text(encoding="utf-8"))
    return []


def _save_markers(markers_file: Path, markers: list[dict]) -> None:
    markers_file.write_text(json.dumps(markers, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_commune_fields(post_text: str) -> dict | None:
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


def _normalize(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def _geocode_commune(commune: str, departement: str) -> tuple[float, float] | None:
    url = (
        f"https://geo.api.gouv.fr/communes?nom={quote_plus(commune)}"
        "&fields=centre,departement&boost=population&limit=5"
    )
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            results = json.loads(r.read())
    except Exception:
        return None
    target = _normalize(departement)
    for r in results:
        if _normalize(r.get("departement", {}).get("nom", "")) == target:
            c = r.get("centre", {}).get("coordinates")
            if c and len(c) == 2:
                return c[1], c[0]
    if results:
        c = results[0].get("centre", {}).get("coordinates")
        if c and len(c) == 2:
            return c[1], c[0]
    return None


# Correspondance type sinistre → couleur (identique à map.html)
# ⚠️ L'ordre compte : 'nappe' doit être testé avant 'inondation' car
# "inondation par remontée de nappe" contient les deux mots.
_TYPE_COLORS = [
    (['sécheresse', 'secheresse', 'rga'], '#E65100'),
    (['nappe'],                            '#00838F'),
    (['inondation', 'coulée', 'coulee'],  '#1565C0'),
    (['avalanche'],                        '#7B1FA2'),
]
_DEFAULT_COLOR = '#546E7A'


def _marker_color(type_str: str) -> str:
    t = (type_str or '').lower()
    for keys, color in _TYPE_COLORS:
        if any(k in t for k in keys):
            return color
    return _DEFAULT_COLOR


def generate_map_thumbnail(markers: list[dict],
                           width: int = 600, height: int = 380) -> bytes | None:
    """Génère une image PNG de la carte avec tous les marqueurs colorés.
    Utilise staticmap + tuiles OpenStreetMap (aucun token requis).
    Retourne None si la génération échoue (le post part quand même sans image)."""
    try:
        from staticmap import StaticMap, CircleMarker
    except ImportError:
        print("  [carte] 'staticmap' non installé — pip install staticmap")
        return None
    try:
        m = StaticMap(
            width, height,
            url_template='https://tile.openstreetmap.org/{z}/{x}/{y}.png',
            headers={
                'User-Agent':
                    'Climat2027-bot/1.0 (+https://github.com/omarce91/Climat2027)'
            }
        )
        for i, marker in enumerate(markers):
            is_latest = (i == len(markers) - 1)
            color = _marker_color(marker.get('type', ''))
            coord = (marker['lon'], marker['lat'])
            if is_latest:
                m.add_marker(CircleMarker(coord, 'white', 24))   # halo blanc
                m.add_marker(CircleMarker(coord, '#FFD700', 20)) # anneau doré
                m.add_marker(CircleMarker(coord, color,   14))   # cercle coloré
            else:
                m.add_marker(CircleMarker(coord, 'white', 12))
                m.add_marker(CircleMarker(coord, color,   9))
        image = m.render()
        buf = io.BytesIO()
        image.save(buf, format='PNG', optimize=True)
        data = buf.getvalue()
        print(f"  [carte] Miniature générée ({len(data)//1024} Ko).")
        return data
    except Exception as e:
        print(f"  [carte] Impossible de générer la miniature : {e}")
        return None


def run_commune_mode(args, client, client_utils, models, map_url: str | None = None) -> None:
    posts_file   = Path(args.commune_posts_file)
    state_file   = Path(args.commune_state_file)
    markers_file = Path(args.markers_file)

    if not posts_file.exists():
        sys.exit(f"Fichier introuvable : {posts_file}")

    posts = _load_commune_posts(posts_file)
    if not posts:
        sys.exit(f"Aucun post #1Jour1CommuneSinistree trouvé dans {posts_file}.")

    state = _load_commune_state(state_file)
    today = date.today().isoformat()

    if state["last_posted_date"] == today and not args.force:
        print(f"Déjà posté aujourd'hui ({today}). Rien à faire.")
        return

    next_index = state["next_index"]
    if next_index >= len(posts):
        print(f"Liste épuisée ({len(posts)}/{len(posts)} posts envoyés).")
        return

    post_text = posts[next_index]
    if len(post_text) > MAX_POST_LENGTH:
        sys.exit(f"Post #{next_index + 1} trop long ({len(post_text)} car.). Corrige posts.md.")

    # Géocodage EN AMONT pour pouvoir construire le lien carte
    fields = _parse_commune_fields(post_text)
    coords = None
    if fields:
        print(f"Géocodage de {fields['commune']} ({fields['departement']})...")
        coords = _geocode_commune(fields["commune"], fields["departement"])
        if coords:
            print(f"  → {coords[0]:.5f}, {coords[1]:.5f}")
        else:
            print("  → échec du géocodage.")

    print(f"--- #1Jour1CommuneSinistree #{next_index + 1}/{len(posts)} ({today}) ---")
    print(post_text)
    if coords and map_url:
        lat, lon = coords
        link = f"{map_url.rstrip('/')}/?lat={lat:.4f}&lon={lon:.4f}&zoom=13"
        print(f"[Lien carte : {link}]")
    print("-" * 50)

    if args.dry_run:
        print("[dry-run] Rien n'a été envoyé.")
        return

    # ── Prépare la liste des marqueurs incluant le nouveau ────────────
    existing_markers = _load_markers(markers_file)
    new_marker = None
    if fields and coords:
        lat, lon = coords
        new_marker = {**fields, "date": today, "lat": lat, "lon": lon}
    updated_markers = existing_markers + ([new_marker] if new_marker else [])

    # ── Génère la miniature de la carte ───────────────────────────────
    thumbnail = None
    if updated_markers:
        print("Génération de la miniature de carte...")
        thumbnail = generate_map_thumbnail(updated_markers)

    # ── Envoi du post principal (avec ou sans miniature) ──────────────
    richtext = build_richtext(client_utils, post_text)
    if thumbnail:
        alt = (f"Carte des communes sinistrées par catastrophe naturelle — "
               f"{fields['commune']} ({fields['departement']}) mis en évidence"
               if fields else "Carte des communes sinistrées")
        result = client.send_image(text=richtext, image=thumbnail, image_alt=alt)
        print("Miniature jointe au post.")
    else:
        result = client.send_post(richtext)

    state["next_index"]        = next_index + 1
    state["last_posted_date"]  = today
    state["posted_log"].append({"index": next_index, "date": today, "uri": result.uri})
    _save_commune_state(state_file, state)
    print(f"Posté : {result.uri}")

    # ── Réponse avec lien carte (best-effort, ne bloque jamais) ──────
    if coords and map_url:
        lat, lon = coords
        link       = f"{map_url.rstrip('/')}/?lat={lat:.4f}&lon={lon:.4f}&zoom=13"
        reply_text = f"📍 Voir {fields['commune']} sur la carte des communes sinistrées #Climat2027\n{link}"
        try:
            parent_ref = models.ComAtprotoRepoStrongRef.Main(
                uri=result.uri, cid=result.cid)
            reply_to   = models.AppBskyFeedPost.ReplyRef(
                root=parent_ref, parent=parent_ref)
            client.send_post(
                text=build_richtext(client_utils, reply_text),
                reply_to=reply_to)
            print(f"Lien carte posté en réponse.")
        except Exception as e:
            print(f"Impossible de poster le lien carte ({e}).")

    # ── Mise à jour de markers.json ───────────────────────────────────
    if new_marker:
        _save_markers(markers_file, updated_markers)
        print(f"Carte : marqueur ajouté pour {fields['commune']} ({coords[0]:.5f}, {coords[1]:.5f})")
    elif fields:
        print(f"Géocodage échoué pour {fields['commune']} — pas de marqueur.")


# ─────────────────────────────────────────────────────────────────────
# Modes POST et REPLY — messages d'engagement #Climat2027
# ─────────────────────────────────────────────────────────────────────

def _load_humor_posts(posts_file: Path) -> list[str]:
    content = posts_file.read_text(encoding="utf-8")
    blocks = [b.strip() for b in re.split(r"\n-{3,}\n", content)]
    return [b for b in blocks if b][1:]


def _load_slogan(slogan_file: Path) -> str:
    return slogan_file.read_text(encoding="utf-8").strip()


def _load_humor_state(state_file: Path) -> dict:
    if state_file.exists():
        return json.loads(state_file.read_text(encoding="utf-8"))
    return {"last_text": None}


def _save_humor_state(state_file: Path, state: dict) -> None:
    state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_stats(stats_file: Path) -> dict:
    if stats_file.exists():
        return json.loads(stats_file.read_text(encoding="utf-8"))
    return {"updated_at": None, "scores": {}}


def _save_stats(stats_file: Path, stats: dict) -> None:
    stats_file.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")


def _text_of(post) -> str:
    record = getattr(post, "record", None)
    return (getattr(record, "text", "") or "") if record else ""


def refresh_stats(client, posts: list[str], slogan: str,
                  stats_file: Path, max_feed_pages: int = 5) -> dict:
    all_texts = set(posts) | {slogan}
    stats  = _load_stats(stats_file)
    scores = stats.get("scores", {})
    cursor = None
    pages = found = 0

    while pages < max_feed_pages:
        params = {"actor": client.me.did, "limit": 100, "filter": "posts_with_replies"}
        if cursor:
            params["cursor"] = cursor
        try:
            resp = client.app.bsky.feed.get_author_feed(params)
        except Exception as e:
            print(f"  [stats] Erreur fil : {e}")
            break

        feed = getattr(resp, "feed", []) or []
        pages += 1
        for item in feed:
            post = getattr(item, "post", None)
            if post is None:
                continue
            text = _text_of(post)
            if text not in all_texts:
                continue
            likes   = getattr(post, "like_count",   0) or 0
            reposts = getattr(post, "repost_count", 0) or 0
            score   = likes + reposts * 2
            entry   = scores.get(text, {"likes": 0, "reposts": 0, "score": 0})
            scores[text] = {
                "likes":   max(entry["likes"],   likes),
                "reposts": max(entry["reposts"], reposts),
                "score":   max(entry["score"],   score),
            }
            found += 1

        if not getattr(resp, "cursor", None):
            break
        cursor = resp.cursor

    stats["updated_at"] = datetime.now(timezone.utc).isoformat()
    stats["scores"]     = scores
    _save_stats(stats_file, stats)
    total = sum(v["score"]   for v in scores.values())
    likes = sum(v["likes"]   for v in scores.values())
    reposts = sum(v["reposts"] for v in scores.values())
    print(f"  [stats] {found} post(s) trouvés / score total {total} (♥{likes} ↺{reposts})")
    return stats


def print_stats(posts: list[str], slogan: str, stats: dict) -> None:
    scores    = stats.get("scores", {})
    all_texts = [(t, scores.get(t, {"likes": 0, "reposts": 0, "score": 0}))
                 for t in (posts + [slogan])]
    all_texts.sort(key=lambda x: -x[1]["score"])
    print("\n" + "─" * 54)
    print(f"  CLASSEMENT #Climat2027 (màj : {stats.get('updated_at','—')[:10]})")
    print("─" * 54)
    for rank, (text, s) in enumerate(all_texts, 1):
        line = text.splitlines()[0][:65]
        print(f"  #{rank:2d} ♥{s['likes']:3d} ↺{s['reposts']:2d} Σ{s['score']:4d}  {line}")
    print("─" * 54 + "\n")


def pick_message(posts: list[str], slogan: str,
                 last_text: str | None, stats: dict) -> str:
    """Tirage pondéré : slogan ~1/3, sinon message selon score.
    Jamais deux fois de suite le même texte.

    Poids d'un message = score moyen des messages connus + son propre score.
    Les messages sans historique démarrent donc au poids moyen et non au
    plancher BASE_WEIGHT, ce qui leur donne immédiatement une chance équitable
    face aux messages déjà établis.
    Si aucun message n'a encore de score, on retombe sur BASE_WEIGHT."""
    if random.random() < SLOGAN_PROBABILITY and slogan != last_text:
        return slogan

    scores     = stats.get("scores", {})
    candidates = [p for p in posts if p != last_text] or posts

    known_scores = [scores[p]["score"] for p in candidates if p in scores and scores[p]["score"] > 0]
    avg_score    = (sum(known_scores) / len(known_scores)) if known_scores else BASE_WEIGHT

    weights = [avg_score + scores.get(p, {}).get("score", 0) for p in candidates]
    return random.choices(candidates, weights=weights, k=1)[0]


def _describe(text: str, posts: list[str], slogan: str, stats: dict) -> str:
    s = stats.get("scores", {}).get(text, {})
    tag = f"♥{s.get('likes',0)} ↺{s.get('reposts',0)}"
    if text == slogan:
        return f"slogan spécial ({tag})"
    return f"message #{posts.index(text)+1}/{len(posts)} ({tag})"


def run_post_mode(args, client, posts, slogan, stats, client_utils) -> None:
    state_file = Path(args.humor_state_file)
    state      = _load_humor_state(state_file)
    post_text  = pick_message(posts, slogan, state.get("last_text"), stats)

    if len(post_text) > MAX_POST_LENGTH:
        sys.exit(f"Message trop long ({len(post_text)} car.).")

    print(f"--- {_describe(post_text, posts, slogan, stats)} ---")
    print(post_text)
    print("-" * 50)

    if args.dry_run:
        print("[dry-run] Rien n'a été envoyé.")
        return

    result = client.send_post(build_richtext(client_utils, post_text))
    state["last_text"] = post_text
    _save_humor_state(state_file, state)
    print(f"Posté : {result.uri}")


# ─── Mode reply ───────────────────────────────────────────────────────

def _get_recent_likes(client, since_dt: datetime) -> list[dict]:
    subjects = []
    cursor = None
    for _ in range(10):
        params = {"repo": client.me.did, "collection": "app.bsky.feed.like", "limit": 100}
        if cursor:
            params["cursor"] = cursor
        resp    = client.com.atproto.repo.list_records(params)
        records = getattr(resp, "records", None)
        if not records:
            break
        stop = False
        for rec in records:
            created_at = datetime.fromisoformat(rec.value.created_at.replace("Z", "+00:00"))
            if created_at < since_dt:
                stop = True
                break
            subjects.append({"uri": rec.value.subject.uri, "cid": rec.value.subject.cid})
        if stop or not getattr(resp, "cursor", None):
            break
        cursor = resp.cursor
    return subjects


def _has_my_reply(thread, my_did: str) -> bool:
    for r in (getattr(thread, "replies", None) or []):
        post = getattr(r, "post", None)
        if post and getattr(post.author, "did", None) == my_did:
            return True
    return False


def _build_reply_refs(models, post):
    parent = models.ComAtprotoRepoStrongRef.Main(uri=post.uri, cid=post.cid)
    rf = getattr(post.record, "reply", None)
    root = models.ComAtprotoRepoStrongRef.Main(
        uri=rf.root.uri, cid=rf.root.cid) if rf else parent
    return root, parent


def run_reply_mode(args, client, posts, slogan, stats, client_utils, models) -> None:
    state_file = Path(args.humor_reply_state_file)
    my_did     = client.me.did
    since_dt   = datetime.now(timezone.utc) - timedelta(hours=args.hours)

    print(f"Recherche des likes depuis {since_dt.isoformat()}...")
    liked = _get_recent_likes(client, since_dt)
    print(f"{len(liked)} post(s) liké(s) dans la fenêtre de {args.hours}h.")

    state = _load_humor_state(state_file)
    sent = skipped = errors = 0

    for subject in liked:
        if sent >= args.max_replies:
            print(f"Limite --max-replies ({args.max_replies}) atteinte.")
            break
        uri = subject["uri"]
        try:
            res = client.get_post_thread(uri=uri, depth=1)
            thread_post = res.thread.post
        except Exception as e:
            print(f"  [ignoré] {uri} ({e})")
            errors += 1
            continue
        if _has_my_reply(res.thread, my_did):
            skipped += 1
            continue

        post_text = pick_message(posts, slogan, state.get("last_text"), stats)
        author    = getattr(thread_post.author, "handle", "?")
        print(f"--- @{author} ← {_describe(post_text, posts, slogan, stats)} ---")
        print(post_text)

        if args.dry_run:
            print("  [dry-run] Rien n'a été envoyé.")
            continue

        try:
            root, parent = _build_reply_refs(models, thread_post)
            reply_to     = models.AppBskyFeedPost.ReplyRef(root=root, parent=parent)
            result_post  = client.send_post(text=build_richtext(client_utils, post_text),
                                            reply_to=reply_to)
        except Exception as e:
            print(f"  [erreur] {e}")
            errors += 1
            continue

        state["last_text"] = post_text
        _save_humor_state(state_file, state)
        sent += 1
        print(f"  Répondu : {result_post.uri}")

        if args.delay > 0:
            print(f"  Pause {args.delay}s...")
            time.sleep(args.delay)

    print(f"Terminé : {sent} envoyé(s), {skipped} déjà répondu(s), {errors} erreur(s).")


# ─────────────────────────────────────────────────────────────────────
# Point d'entrée
# ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Script central #Climat2027 — commune (défaut), post, reply."
    )
    parser.add_argument("--mode", choices=["all", "commune", "post", "reply"],
                        default="all",
                        help="Mode d'exécution (défaut : all = commune + stats + reply)")
    parser.add_argument("--config", default="credentials.json")
    parser.add_argument("--dry-run", action="store_true")

    # Mode commune
    grp_c = parser.add_argument_group("mode commune")
    grp_c.add_argument("--commune-posts-file",  default="posts.md")
    grp_c.add_argument("--commune-state-file",  default="state.json")
    grp_c.add_argument("--markers-file",        default="markers.json")
    grp_c.add_argument("--map-url",             default=None,
                       help="URL de base de la carte (ex: https://compte.github.io/repo/). "
                            "Si absent, lu depuis credentials.json (champ 'map_url').")
    grp_c.add_argument("--force", action="store_true",
                       help="Ignore la limite 1 post/jour")

    # Modes post + reply
    grp_h = parser.add_argument_group("modes post et reply")
    grp_h.add_argument("--humor-posts-file",       default="humor_posts.md")
    grp_h.add_argument("--slogan-file",            default="slogan.txt")
    grp_h.add_argument("--stats-file",             default="humor_stats.json")
    grp_h.add_argument("--humor-state-file",       default="humor_state.json")
    grp_h.add_argument("--humor-reply-state-file", default="humor_reply_state.json")
    grp_h.add_argument("--stats-only",  action="store_true",
                       help="Affiche le classement sans poster")
    grp_h.add_argument("--show-stats",  action="store_true",
                       help="Affiche le classement après l'envoi")

    # Mode reply seulement
    grp_r = parser.add_argument_group("mode reply")
    grp_r.add_argument("--hours",       type=float, default=24)
    grp_r.add_argument("--max-replies", type=int,   default=10)
    grp_r.add_argument("--delay",       type=float, default=DEFAULT_DELAY)

    args = parser.parse_args()

    # ── Mode all : commune + stats + reply ───────────────────────────
    if args.mode == "all":
        handle, app_password, cred_map_url = load_credentials(Path(args.config))
        map_url = args.map_url or cred_map_url
        try:
            from atproto import Client, client_utils, models
        except ImportError:
            sys.exit("pip install atproto")
        client = Client()
        client.login(handle, app_password)

        print("═" * 50)
        print("1/3 — Post #1Jour1CommuneSinistree")
        print("═" * 50)
        run_commune_mode(args, client, client_utils, models, map_url)

        for f in [Path(args.humor_posts_file), Path(args.slogan_file)]:
            if not f.exists():
                print(f"[avertissement] Fichier introuvable : {f} — étapes 2/3 ignorées.")
                return

        posts  = _load_humor_posts(Path(args.humor_posts_file))
        slogan = _load_slogan(Path(args.slogan_file))

        print()
        print("═" * 50)
        print("2/3 — Mise à jour des stats d'engagement")
        print("═" * 50)
        if not args.dry_run:
            stats = refresh_stats(client, posts, slogan, Path(args.stats_file))
        else:
            stats = _load_stats(Path(args.stats_file))
            print("[dry-run] Stats non rafraîchies.")

        if args.show_stats:
            print_stats(posts, slogan, stats)

        print()
        print("═" * 50)
        print("3/3 — Réponses aux likes récents")
        print("═" * 50)
        run_reply_mode(args, client, posts, slogan, stats, client_utils, models)
        return

    # ── Mode commune seul ─────────────────────────────────────────────
    if args.mode == "commune":
        handle, app_password, cred_map_url = load_credentials(Path(args.config))
        map_url = args.map_url or cred_map_url
        try:
            from atproto import Client, client_utils, models
        except ImportError:
            sys.exit("pip install atproto")
        client = Client()
        client.login(handle, app_password)
        run_commune_mode(args, client, client_utils, models, map_url)
        return

    # ── Modes post / reply / stats-only ──────────────────────────────
    for f in [Path(args.humor_posts_file), Path(args.slogan_file)]:
        if not f.exists():
            sys.exit(f"Fichier introuvable : {f}")

    posts  = _load_humor_posts(Path(args.humor_posts_file))
    slogan = _load_slogan(Path(args.slogan_file))
    if not posts:
        sys.exit(f"Aucun message trouvé dans {args.humor_posts_file}.")

    handle, app_password, _ = load_credentials(Path(args.config))
    try:
        from atproto import Client, client_utils, models
    except ImportError:
        sys.exit("pip install atproto")
    client = Client()
    client.login(handle, app_password)

    if not args.dry_run:
        print("Mise à jour des stats...")
        stats = refresh_stats(client, posts, slogan, Path(args.stats_file))
    else:
        stats = _load_stats(Path(args.stats_file))

    if args.stats_only or args.show_stats:
        print_stats(posts, slogan, stats)

    if args.stats_only:
        return

    if args.mode == "post":
        run_post_mode(args, client, posts, slogan, stats, client_utils)
    else:
        run_reply_mode(args, client, posts, slogan, stats, client_utils, models)

    if args.show_stats:
        print_stats(posts, slogan, _load_stats(Path(args.stats_file)))


if __name__ == "__main__":
    main()

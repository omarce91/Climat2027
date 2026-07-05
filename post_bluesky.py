#!/usr/bin/env python3
"""
Poste automatiquement le PROCHAIN post de la liste sur Bluesky.
Ne poste jamais plus d'une fois par jour, même si le script est relancé
plusieurs fois (cron qui tourne deux fois, lancement manuel en double, etc.).

----------------------------------------------------------------------
Pré-requis
----------------------------------------------------------------------
    pip install atproto

Identifiants Bluesky lus depuis un fichier JSON (credentials.json par
défaut, jamais le mot de passe principal du compte, toujours un "app
password" généré dans Bluesky > Réglages > Confidentialité et sécurité
> App passwords) :

    {
        "handle": "climat2027.bsky.social",
        "app_password": "xxxx-xxxx-xxxx-xxxx"
    }

⚠️  Ce fichier contient un secret : ne jamais le commiter dans un dépôt
    git (ajoute-le à .gitignore) et restreins ses droits de lecture,
    par exemple sous Linux/macOS : chmod 600 credentials.json

----------------------------------------------------------------------
Usage
----------------------------------------------------------------------
    # Test sans rien envoyer (à faire en premier)
    python post_bluesky.py --dry-run

    # Envoi réel
    python post_bluesky.py

    # Fichiers personnalisés
    python post_bluesky.py --posts-file posts.md --state-file state.json --config credentials.json
"""

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

MAX_POST_LENGTH = 300  # limite Bluesky (en graphèmes ; approximation via len())


def load_posts(posts_file: Path) -> list[str]:
    """Découpe le fichier markdown en liste de posts.
    Un post = un bloc séparé par une ligne '---', et qui commence
    par le hashtag #1Jour1CommuneSinistree (ça exclut le bloc d'en-tête)."""
    content = posts_file.read_text(encoding="utf-8")
    blocks = re.split(r"\n-{3,}\n", content)
    posts = []
    for block in blocks:
        block = block.strip()
        if block.startswith("#1Jour1CommuneSinistree"):
            posts.append(block)
    return posts


def load_state(state_file: Path) -> dict:
    if state_file.exists():
        return json.loads(state_file.read_text(encoding="utf-8"))
    return {"next_index": 0, "last_posted_date": None, "posted_log": []}


def save_state(state_file: Path, state: dict) -> None:
    state_file.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_credentials(config_file: Path) -> tuple[str, str]:
    """Lit le handle et l'app password Bluesky depuis un fichier JSON.

    Format attendu :
        {
            "handle": "climat2027.bsky.social",
            "app_password": "xxxx-xxxx-xxxx-xxxx"
        }
    """
    if not config_file.exists():
        sys.exit(
            f"Fichier d'identifiants introuvable : {config_file}\n"
            "Crée-le sur ce modèle :\n"
            '{\n  "handle": "ton-compte.bsky.social",\n'
            '  "app_password": "xxxx-xxxx-xxxx-xxxx"\n}'
        )
    try:
        data = json.loads(config_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"Fichier d'identifiants invalide ({config_file}) : {e}")

    handle = data.get("handle")
    app_password = data.get("app_password")
    if not handle or not app_password:
        sys.exit(
            f"Le fichier {config_file} doit contenir les clés "
            "'handle' et 'app_password'."
        )
    return handle, app_password


def build_richtext(client_utils, text: str):
    """Reconstruit le post avec les hashtags rendus cliquables sur Bluesky."""
    builder = client_utils.TextBuilder()
    tokens = re.split(r"(#\w+)", text)
    for tok in tokens:
        if tok.startswith("#") and len(tok) > 1:
            builder.tag(tok, tok[1:])
        else:
            builder.text(tok)
    return builder


def main():
    parser = argparse.ArgumentParser(
        description="Poste le prochain post de la liste sur Bluesky (1 par jour max)."
    )
    parser.add_argument("--posts-file", default="posts.md")
    parser.add_argument("--state-file", default="state.json")
    parser.add_argument(
        "--config", default="credentials.json",
        help="Fichier JSON contenant 'handle' et 'app_password'"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="N'envoie rien, affiche seulement ce qui serait posté"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Ignore la limite d'un post/jour (à utiliser avec prudence)"
    )
    args = parser.parse_args()

    posts_file = Path(args.posts_file)
    state_file = Path(args.state_file)

    if not posts_file.exists():
        sys.exit(f"Fichier introuvable : {posts_file}")

    posts = load_posts(posts_file)
    if not posts:
        sys.exit(f"Aucun post trouvé dans {posts_file}.")

    state = load_state(state_file)
    today = date.today().isoformat()

    # Règle d'or : jamais plus d'un post par jour
    if state["last_posted_date"] == today and not args.force:
        print(f"Déjà posté aujourd'hui ({today}). Rien à faire.")
        return

    next_index = state["next_index"]
    if next_index >= len(posts):
        print(
            "Tous les posts ont déjà été envoyés "
            f"({len(posts)}/{len(posts)}). Liste épuisée."
        )
        return

    post_text = posts[next_index]

    if len(post_text) > MAX_POST_LENGTH:
        sys.exit(
            f"Le post #{next_index + 1} dépasse {MAX_POST_LENGTH} caractères "
            f"({len(post_text)}). Corrige le fichier avant de continuer."
        )

    print(f"--- Post #{next_index + 1}/{len(posts)} ({today}) ---")
    print(post_text)
    print("---------------------------------")

    if args.dry_run:
        print("[dry-run] Rien n'a été envoyé. État non modifié.")
        return

    handle, app_password = load_credentials(Path(args.config))

    try:
        from atproto import Client, client_utils
    except ImportError:
        sys.exit("Le paquet 'atproto' n'est pas installé. Lance : pip install atproto")

    client = Client()
    client.login(handle, app_password)

    richtext = build_richtext(client_utils, post_text)
    result = client.send_post(richtext)

    # On ne met à jour l'état QUE si l'envoi a réussi
    state["next_index"] = next_index + 1
    state["last_posted_date"] = today
    state["posted_log"].append(
        {"index": next_index, "date": today, "uri": result.uri}
    )
    save_state(state_file, state)

    print(f"Posté avec succès : {result.uri}")


if __name__ == "__main__":
    main()

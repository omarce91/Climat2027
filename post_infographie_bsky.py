#!/usr/bin/env python3
"""
Poste l'infographie og_image.jpg sur climat2027.bsky.social chaque dimanche.

Affiche dans le post le nombre de dimanches restant avant le 1er tour
de la présidentielle (18 avril 2027).

Usage :
    python post_infographie_bsky.py
    python post_infographie_bsky.py --image images/og_image.jpg
    python post_infographie_bsky.py --dry-run

Credentials lus depuis credentials.json ou variables d'env
  BSKY_C27_HANDLE / BSKY_C27_APP_PASSWORD.
"""

import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

PREMIER_TOUR = date(2027, 4, 18)
IMAGE_DEFAULT = Path("images/og_image.jpg")


# ── Calcul du compte à rebours ────────────────────────────────────────────────

def count_sundays(start: date, end: date) -> int:
    """Nombre de dimanches entre start (exclu) et end (exclu)."""
    d, n = start + timedelta(days=1), 0
    while d < end:
        if d.weekday() == 6:
            n += 1
        d += timedelta(days=1)
    return n


# ── Texte du post ─────────────────────────────────────────────────────────────

def build_post_text(sundays: int) -> str:
    s = "s" if sundays > 1 else ""
    return (
        f"🗓️ {sundays} dimanche{s} avant le 1er tour (18 avril 2027)\n\n"
        "Où en sont les candidats sur le climat ? "
        "Ambition d'atténuation (axe X) vs adaptation (axe Y), "
        "taille des bulles = intentions de vote.\n\n"
        "#Climat2027 #Présidentielle2027"
    )


# ── Credentials ───────────────────────────────────────────────────────────────

def load_credentials(config_path: Path) -> tuple[str, str]:
    """Retourne (handle_c27, app_password_c27) depuis credentials.json ou env."""
    handle = os.environ.get("BSKY_C27_HANDLE", "")
    pw     = os.environ.get("BSKY_C27_APP_PASSWORD", "")

    if config_path.exists():
        try:
            data = json.loads(config_path.read_text())
            handle = handle or data.get("handle_c27", "")
            pw     = pw     or data.get("app_password_c27", "")
        except Exception as e:
            print(f"[avertissement] Lecture credentials.json : {e}", file=sys.stderr)

    if not handle or not pw:
        sys.exit(
            "Credentials manquants. Renseigne handle_c27 / app_password_c27 dans "
            "credentials.json ou via BSKY_C27_HANDLE / BSKY_C27_APP_PASSWORD."
        )
    return handle, pw


# ── Publication Bluesky ───────────────────────────────────────────────────────

def post_to_bluesky(handle: str, app_password: str,
                    image_path: Path, text: str, dry_run: bool) -> None:
    try:
        from atproto import Client, client_utils
    except ImportError:
        sys.exit("pip install atproto")

    print(f"Connexion à Bluesky en tant que {handle}…")
    client = Client()
    client.login(handle, app_password)

    print("Texte du post :")
    print("─" * 50)
    print(text)
    print("─" * 50)

    if dry_run:
        print("[dry-run] Aucun post envoyé.")
        return

    # Upload de l'image
    print(f"Upload de l'image {image_path}…")
    with open(image_path, "rb") as f:
        img_data = f.read()

    upload = client.upload_blob(img_data)
    blob   = upload.blob

    # Construction du post avec image (embed images)
    from atproto import models

    image_embed = models.AppBskyEmbedImages.Main(
        images=[
            models.AppBskyEmbedImages.Image(
                alt="Infographie #Climat2027 — comparaison des programmes des candidats",
                image=blob,
                aspect_ratio=models.AppBskyEmbedImages.AspectRatio(
                    width=1200, height=630
                ),
            )
        ]
    )

    tb  = client_utils.TextBuilder()
    tb.text(text)

    response = client.send_post(text=tb, embed=image_embed)
    print(f"✓ Post publié : {response.uri}")


# ── Point d'entrée ────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Poste l'infographie og_image.jpg sur climat2027.bsky.social."
    )
    parser.add_argument("--image", default=str(IMAGE_DEFAULT),
                        help=f"Chemin de l'image (défaut : {IMAGE_DEFAULT})")
    parser.add_argument("--config", default="credentials.json",
                        help="Fichier de credentials (défaut : credentials.json)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Affiche le texte sans poster")
    args = parser.parse_args()

    image_path = Path(args.image)
    if not image_path.exists():
        sys.exit(f"Image introuvable : {image_path}")

    today   = date.today()
    sundays = count_sundays(today, PREMIER_TOUR)
    text    = build_post_text(sundays)

    handle, app_password = load_credentials(Path(args.config))
    post_to_bluesky(handle, app_password, image_path, text, dry_run=args.dry_run)


if __name__ == "__main__":
    main()

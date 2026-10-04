#!/usr/bin/env python3
"""
Poste la carte #CommunesSinistreesDuJour sur Bluesky (compte climat2027).
Appelé par GitHub Actions — remplace le heredoc inline du workflow.

Usage :
    python post_gaspar_bluesky.py --gaspar catnat_gaspar_2026-07-08.csv
"""
import argparse, glob, sys
from pathlib import Path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gaspar", default=None,
                        help="Chemin vers le CSV GASPAR (auto-détecté si absent)")
    parser.add_argument("--config", default="credentials.json")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    # Auto-détection du CSV GASPAR
    gaspar_csv = args.gaspar
    if not gaspar_csv:
        found = sorted(glob.glob("catnat_gaspar*.csv"))
        if not found:
            print("Aucun CSV GASPAR trouvé — carte ignorée.")
            sys.exit(0)
        gaspar_csv = found[-1]
        print(f"CSV GASPAR détecté : {gaspar_csv}")

    from climat2027 import (
        load_credentials, ensure_gaspar_cache, post_gaspar_map
    )
    try:
        from atproto import client_utils
    except ImportError:
        sys.exit("pip install atproto")

    (handle, app_password,
     handle_c27, app_password_c27,
     _, _) = load_credentials(Path(args.config))

    from climat2027 import _login_clients
    client_omarce, client_c27 = _login_clients(
        handle, app_password, handle_c27, app_password_c27
    )

    cache_file = Path("commune_coords_cache.json")
    ensure_gaspar_cache(Path(gaspar_csv), cache_file)

    post_gaspar_map(
        client_c27, client_omarce, client_utils,
        gaspar_csv        = Path(gaspar_csv),
        coords_cache_file = cache_file,
        gaspar_state_file = Path("gaspar_map_state.json"),
        dry_run           = args.dry_run,
    )

if __name__ == "__main__":
    main()

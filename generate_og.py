#!/usr/bin/env python3
"""
Génère l'image Open Graph (og_image.jpg, 1200×630 px) pour #Climat2027.

Lance chaque dimanche par GitHub Actions pour mettre à jour la date
et le compte à rebours avant le 1er tour (18 avril 2027).

Usage :
    python generate_og.py                        # → images/og_image.jpg
    python generate_og.py --out autre/chemin.jpg
"""

import argparse
import math
from datetime import date, timedelta
from pathlib import Path

# ── Données candidats (positions au 4 oct. 2026) ─────────────────────
CANDIDATS = [
    {"s": "ÉELV",  "att": 9.2, "adp": 8.1, "b": 20, "mk": "o", "c": "#4ecb71"},
    {"s": "G.Éco", "att": 8.1, "adp": 6.5, "b": 8,  "mk": "o", "c": "#4ecb71"},
    {"s": "PP/PS", "att": 6.5, "adp": 7.9, "b": 10, "mk": "o", "c": "#ff6eb4"},
    {"s": "LFI",   "att": 8.5, "adp": 7.6, "b": 40, "mk": "h", "c": "#ff5555"},
    {"s": "PCF",   "att": 6.4, "adp": 5.4, "b": 5,  "mk": "h", "c": "#ff5555"},
    {"s": "PS",    "att": 5.0, "adp": 6.6, "b": 3,  "mk": "h", "c": "#ff6eb4"},
    {"s": "LO",    "att": 4.0, "adp": 2.1, "b": 0.5,"mk": "h", "c": "#cc4444"},
    {"s": "Hor.",  "att": 4.5, "adp": 8.3, "b": 2,  "mk": "h", "c": "#f0b429"},
    {"s": "Ren.",  "att": 3.0, "adp": 4.4, "b": 1,  "mk": "h", "c": "#f0b429"},
    {"s": "Ind.",  "att": 3.6, "adp": 4.1, "b": 0.5,"mk": "h", "c": "#f0b429"},
    {"s": "LR",    "att": 2.6, "adp": 4.0, "b": 0.5,"mk": "h", "c": "#5b9bd5"},
    {"s": "LR",    "att": 2.4, "adp": 3.4, "b": 0.5,"mk": "h", "c": "#5b9bd5"},
    {"s": "Ind.D", "att": 1.7, "adp": 2.7, "b": 0.3,"mk": "^", "c": "#5b9bd5"},
    {"s": "RN",    "att": 0.9, "adp": 1.9, "b": 0.2,"mk": "^", "c": "#8899cc"},
    {"s": "Rec.",  "att": 0.4, "adp": 0.8, "b": 0.1,"mk": "^", "c": "#8899cc"},
    {"s": "DLF",   "att": 1.1, "adp": 1.2, "b": 0.2,"mk": "^", "c": "#8899cc"},
]

PREMIER_TOUR = date(2027, 4, 18)

BG      = "#132218"
BGC     = "#0f1c13"
GRID    = "#1e3826"
ACCENT  = "#4ecb71"
LBL     = "#7aaa88"
INK     = "#9abfa2"
MUTED   = "#4a7a5a"


def count_sundays(start: date, end: date) -> int:
    """Nombre de dimanches entre start (exclu) et end (exclu)."""
    d, n = start + timedelta(days=1), 0
    while d < end:
        if d.weekday() == 6:
            n += 1
        d += timedelta(days=1)
    return n


def generate(output: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.lines as mlines

    today    = date.today()
    sundays  = count_sundays(today, PREMIER_TOUR)
    date_str = today.strftime("%-d %B %Y")          # Linux
    try:
        date_str = today.strftime("%-d %B %Y")
    except ValueError:
        date_str = today.strftime("%d %B %Y").lstrip("0")

    fig = plt.figure(figsize=(12, 6.3), dpi=100, facecolor=BG)
    ax  = fig.add_axes([0.055, 0.13, 0.91, 0.65])
    ax.set_facecolor(BGC)
    for sp in ax.spines.values():
        sp.set_edgecolor(GRID)

    ax.set_xlim(-0.3, 10.3)
    ax.set_ylim(-0.3, 10.3)
    ax.grid(True, color=GRID, linewidth=0.6, alpha=0.9)
    ax.set_axisbelow(True)

    tl = {0: "Nulle", 2: "Faible", 4: "Modérée",
          6: "Forte", 8: "Très forte", 10: "Maximale"}
    ax.set_xticks(list(tl.keys()))
    ax.set_xticklabels(list(tl.values()), color=MUTED, fontsize=7)
    ax.set_yticks(list(tl.keys()))
    ax.set_yticklabels(list(tl.values()), color=MUTED, fontsize=7)
    ax.tick_params(colors=GRID, length=2)
    ax.set_xlabel("Atténuation — ambition de réduction des émissions →",
                  color=LBL, fontsize=8.5, labelpad=3)
    ax.set_ylabel("Adaptation →", color=LBL, fontsize=8.5, labelpad=3)
    ax.axvline(5, color="#2a4a36", lw=0.8, ls="--", alpha=0.7)
    ax.axhline(5, color="#2a4a36", lw=0.8, ls="--", alpha=0.7)
    for txt, x, y in [
        ("Fort sur les deux axes", 5.1, 9.7),
        ("Peu sur les deux axes",  4.9, 0.3),
    ]:
        ax.text(x, y, txt, color="#2a4a36", fontsize=7,
                ha="left" if x > 5 else "right")

    for c in CANDIDATS:
        r  = max(6, 3.5 + math.sqrt(c["b"]) * 4.2)
        sz = (r * 1.8) ** 2
        ax.scatter(c["att"], c["adp"], s=sz, c=c["c"],
                   marker=c["mk"], alpha=0.88, edgecolors="none", zorder=3)
        off = r * 1.8 * 0.55 + 4
        ax.annotate(c["s"], (c["att"], c["adp"]),
                    textcoords="offset points", xytext=(0, off),
                    ha="center", fontsize=6.5, color=INK,
                    fontweight="500", zorder=4)

    leg_el = [
        mlines.Line2D([], [], marker="o", ls="", c="#4ecb71", ms=7, label="Écologistes"),
        mlines.Line2D([], [], marker="h", ls="", c="#ff5555", ms=7, label="LFI/PCF"),
        mlines.Line2D([], [], marker="h", ls="", c="#ff6eb4", ms=7, label="PS/PP"),
        mlines.Line2D([], [], marker="h", ls="", c="#f0b429", ms=7, label="Centre"),
        mlines.Line2D([], [], marker="h", ls="", c="#5b9bd5", ms=7, label="Droite"),
        mlines.Line2D([], [], marker="^", ls="", c="#8899cc", ms=7, label="Extr. droite"),
    ]
    ax.legend(handles=leg_el, loc="lower right", fontsize=7,
              facecolor="#1a3020", edgecolor="#2a4a36",
              labelcolor=INK, framealpha=0.92,
              borderpad=0.6, handlelength=1.2, handletextpad=0.5)

    # En-tête
    fig.text(0.055, 0.975, "#Climat2027",
             fontsize=21, fontweight="bold", color=ACCENT, ha="left", va="top")
    fig.text(0.055, 0.893,
             "Comparaison des programmes des candidats déclarés concernant le climat.",
             fontsize=9.5, color=LBL, ha="left", va="top")

    # Pied
    fig.text(0.055, 0.025,
             f"{date_str}  ·  {sundays} dimanches avant le 1er tour  ·  18 avril 2027",
             fontsize=7.5, color=MUTED, ha="left", va="bottom")
    fig.text(0.955, 0.025, "climat2027.fr",
             fontsize=9, color=ACCENT, ha="right", va="bottom", fontweight="bold")

    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(output), dpi=100, facecolor=BG,
                format="jpeg", pil_kwargs={"quality": 93, "optimize": True})
    plt.close(fig)
    print(f"✓ {output}  ({output.stat().st_size // 1024} Ko)  —  {date_str}, {sundays} dimanches")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Génère og_image.jpg pour #Climat2027 (date du jour, compte à rebours)."
    )
    parser.add_argument("--out", default="images/og_image.jpg",
                        help="Chemin de sortie (défaut : images/og_image.jpg)")
    args = parser.parse_args()
    generate(Path(args.out))


if __name__ == "__main__":
    main()

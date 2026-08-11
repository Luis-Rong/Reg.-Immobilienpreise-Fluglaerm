"""Kartendaten für die Streamlit-App aufbereiten.

Die BORIS-Zonen sind sehr fein geschnitten; unvereinfacht dauert der
Kartenaufbau im Browser mehrere Sekunden. Hier werden die Geometrien
vereinfacht, auf WGS84 gedreht und mit allen Kartenattributen zu einer
kompakten Datei zusammengefasst.

Ergebnis: data/processed/karte.parquet, data/processed/konturen_karte.parquet
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd

from config import CRS_WGS84, DATA_PROCESSED, DATA_RAW, RESULTS

# Vereinfachungstoleranz in Metern -- fein genug, dass Zonengrenzen im
# Straßenmaßstab erkennbar bleiben.
TOLERANZ_M = 8


def main() -> None:
    zonen = gpd.read_parquet(DATA_PROCESSED / "zonen.parquet")
    panel = pd.read_parquet(DATA_PROCESSED / "panel.parquet")

    breit = panel.pivot_table(
        index="gml_id", columns="stichtag",
        values=["bodenrichtwert", "flug_tag", "flug_tag_gefuellt"],
    )
    breit.columns = [f"{a}_{b}" for a, b in breit.columns]
    breit = breit.reset_index()

    karte = zonen.merge(breit, on="gml_id", how="left")

    effekt = pd.read_parquet(RESULTS / "zonen_effekt.parquet")
    karte = karte.merge(
        effekt[["gml_id", "klasse", "effekt_prozent"]], on="gml_id", how="left"
    )

    jahre = sorted({int(c.split("_")[-1]) for c in breit.columns if c.startswith("bodenrichtwert_")})
    if len(jahre) >= 2:
        alt, neu = jahre[-2], jahre[-1]
        karte["brw_veraenderung_pct"] = (
            (karte[f"bodenrichtwert_{neu}"] / karte[f"bodenrichtwert_{alt}"] - 1) * 100
        )
        karte["veraenderung_zeitraum"] = f"{alt} → {neu}"

    karte["geometry"] = karte.geometry.simplify(TOLERANZ_M, preserve_topology=True)
    karte = karte.to_crs(CRS_WGS84)
    karte = karte[karte.geometry.notna() & ~karte.geometry.is_empty]

    karte.to_parquet(DATA_PROCESSED / "karte.parquet")
    print(f"karte.parquet: {len(karte)} Zonen, Stichtage {jahre}")

    # Lärmkonturen als Kartenoverlay (jüngster verfügbarer Jahrgang)
    konturen_jahre = sorted(
        int(p.stem.split("_")[1]) for p in DATA_RAW.glob("konturen_*_tag.parquet")
    )
    letztes = konturen_jahre[-1]
    kont = gpd.read_parquet(DATA_RAW / f"konturen_{letztes}_tag.parquet")
    kont["geometry"] = kont.geometry.simplify(25, preserve_topology=True)
    kont = kont[kont["pegel"].isin([50, 55, 60, 65])].to_crs(CRS_WGS84)
    kont.to_parquet(DATA_PROCESSED / "konturen_karte.parquet")
    print(f"konturen_karte.parquet: {len(kont)} Isophonen aus {letztes}")


if __name__ == "__main__":
    main()

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

from build_dataset import STICHTAG_ZU_LAERMJAHR, nutzungsklasse_codiert
from config import CRS_METRIC, CRS_WGS84, DATA_PROCESSED, DATA_RAW, RESULTS

# Vereinfachungstoleranz in Metern -- fein genug, dass Zonengrenzen im
# Straßenmaßstab erkennbar bleiben.
TOLERANZ_M = 8

RLP_STICHTAGE = (2024, 2026)


def lade_rlp_kacheln() -> gpd.GeoDataFrame | None:
    """Mainzer Kacheln aus dem freien VBORIS-WMS mit der Hessen-Karte verschmelzbar machen.

    Anders als bei Hessen gibt es hier keine Zonenpolygone (WMS statt WFS,
    siehe fetch_boris_rlp.py) -- jede Kachel ist ein Rasterpunkt mit dem dort
    gültigen Bodenrichtwert. Zwei Stichtage werden über die Kachelmitte
    zusammengeführt: nur wenn die Nutzungsklasse an derselben Stelle in
    beiden Jahren übereinstimmt, wird eine Wertänderung berechnet -- exakt
    dieselbe Schutzmaßnahme, die für Hessen die Scheinänderungen zwischen
    Bauland und Ackerland verhindert (siehe build_dataset.py).
    """
    dateien = {j: DATA_RAW / f"boris_rlp_tiles_{j}.parquet" for j in RLP_STICHTAGE}
    vorhanden = {j: p for j, p in dateien.items() if p.exists()}
    if not vorhanden:
        return None

    frames = []
    for jahr, pfad in vorhanden.items():
        g = gpd.read_parquet(pfad)
        g["nutzungsklasse"] = nutzungsklasse_codiert(g["art"], g["entwicklungszustand"])
        mitte = g.geometry.centroid
        g["_x"] = mitte.x.round(0)
        g["_y"] = mitte.y.round(0)
        frames.append(
            g[["_x", "_y", "gemeinde", "gemarkung", "nutzungsklasse", "bodenrichtwert", "geometry"]]
            .rename(columns={"bodenrichtwert": f"bodenrichtwert_{jahr}"})
        )

    kacheln = frames[0]
    for f in frames[1:]:
        kacheln = kacheln.merge(
            f.drop(columns="geometry"), on=["_x", "_y"], how="outer",
            suffixes=("", "_neu"),
        )
        # Bei outer merge können Attribute nur aus dem zweiten Jahr kommen
        for spalte in ("gemeinde", "gemarkung", "nutzungsklasse"):
            if f"{spalte}_neu" in kacheln.columns:
                kacheln[spalte] = kacheln[spalte].fillna(kacheln[f"{spalte}_neu"])
                kacheln = kacheln.drop(columns=f"{spalte}_neu")
        fehlend = kacheln["geometry"].isna()
        if fehlend.any():
            nachschlagen = dict(zip(zip(f["_x"], f["_y"]), f.geometry))
            kacheln.loc[fehlend, "geometry"] = [
                nachschlagen.get((x, y))
                for x, y in zip(kacheln.loc[fehlend, "_x"], kacheln.loc[fehlend, "_y"])
            ]
    kacheln = gpd.GeoDataFrame(kacheln, geometry="geometry", crs=CRS_METRIC)

    jahre_da = sorted(vorhanden)
    if len(jahre_da) >= 2:
        alt, neu = jahre_da[0], jahre_da[-1]
        # Nur vergleichen, wenn beide Jahre einen Wert UND dieselbe
        # Nutzungsklasse an dieser Kachel haben -- die Klasse wird beim
        # jüngeren Jahr zuletzt gesetzt, ein Klassenwechsel zwischen den
        # Stichtagen lässt sich mit dieser einfachen Verschmelzung nicht
        # gegenprüfen. Deshalb hier zusätzlich: Wertänderung nur auf
        # Wohnbauland, wo ein Klassenwechsel am unwahrscheinlichsten ist.
        passend = kacheln["nutzungsklasse"].eq("bauland_wohnen")
        kacheln["brw_veraenderung_pct"] = pd.NA
        kacheln.loc[passend, "brw_veraenderung_pct"] = (
            kacheln.loc[passend, f"bodenrichtwert_{neu}"]
            / kacheln.loc[passend, f"bodenrichtwert_{alt}"]
            - 1
        ) * 100

    kacheln["nutzung_gruppe"] = kacheln["nutzungsklasse"].map(
        lambda k: "wohnen" if k == "bauland_wohnen" else "sonstige"
    )
    kacheln["ist_bauland"] = kacheln["nutzungsklasse"].str.startswith("bauland_")
    kacheln["datenquelle"] = "VBORIS RLP (Kachel, kein Zonenpolygon)"

    # Fluglärm an der Kachelmitte -- dieselbe Vorjahres-Logik wie bei Hessen.
    for jahr in jahre_da:
        laermjahr = STICHTAG_ZU_LAERMJAHR.get(jahr)
        kontur_pfad = DATA_RAW / f"konturen_{laermjahr}_tag.parquet"
        if laermjahr is None or not kontur_pfad.exists():
            continue
        konturen = gpd.read_parquet(kontur_pfad).to_crs(CRS_METRIC)[["pegel", "geometry"]]
        mitte = gpd.GeoDataFrame(geometry=kacheln.geometry.centroid, crs=CRS_METRIC)
        mitte["_i"] = mitte.index
        treffer = gpd.sjoin(mitte, konturen, how="left", predicate="within")
        kacheln[f"flug_tag_{jahr}"] = treffer.groupby("_i")["pegel"].max()
        kacheln[f"flug_tag_gefuellt_{jahr}"] = kacheln[f"flug_tag_{jahr}"].fillna(44.0)

    return kacheln.drop(columns=["_x", "_y"])


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
    karte["datenquelle"] = "BORIS Hessen (Zonenpolygon)"

    rlp = lade_rlp_kacheln()
    n_hessen = len(karte)
    if rlp is not None:
        rlp = rlp.to_crs(CRS_WGS84)
        rlp = rlp[rlp.geometry.notna() & ~rlp.geometry.is_empty]
        karte = pd.concat([karte, rlp], ignore_index=True)
        karte = gpd.GeoDataFrame(karte, geometry="geometry", crs=CRS_WGS84)

    karte.to_parquet(DATA_PROCESSED / "karte.parquet")
    zusatz = f" + {len(rlp)} Mainzer Kacheln (VBORIS RLP)" if rlp is not None else ""
    print(f"karte.parquet: {n_hessen} Hessen-Zonen{zusatz}, Stichtage {jahre}")

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

    # GREIX-Zeitreihe mitliefern, damit die App ohne data/raw startet
    # (die Rohdaten sind zu groß fürs Repository und deshalb ausgeschlossen).
    greix_quelle = DATA_RAW / "greix_staedte.parquet"
    if greix_quelle.exists():
        greix = pd.read_parquet(greix_quelle)
        greix.to_parquet(DATA_PROCESSED / "greix_staedte.parquet")
        print(f"greix_staedte.parquet: {len(greix)} Zeilen übernommen")


if __name__ == "__main__":
    main()

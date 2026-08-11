"""Analyse-Datensatz aus Bodenrichtwerten, Lärmkonturen und Kontrollvariablen.

Aufbau als Standort-Panel: Die Zonenzuschnitte von BORIS ändern sich zwischen
den Stichtagen, und die Zonen-IDs sind nicht stabil (die Schnittmenge der
IDs von 2022 und 2024 ist leer). Verfolgt wird deshalb nicht die
Verwaltungseinheit, sondern der Ort: Referenz sind die Zonen des Stichtags
2024; für jeden anderen Stichtag wird der Wert derjenigen Zone übernommen,
die den Repräsentativpunkt der Referenzzone enthält.

Der Lärm wird jeweils dem Kalenderjahr VOR dem Stichtag entnommen -- der
Bodenrichtwert zum 01.01.2024 spiegelt die Marktlage des Jahres 2023.

Ergebnis:
  data/processed/panel.parquet   Standort x Stichtag (lang)
  data/processed/zonen.parquet   Referenzgeometrien mit Kontrollvariablen
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd

from config import (
    CRS_METRIC,
    DATA_PROCESSED,
    DATA_RAW,
    LDEN_BINS,
    LDEN_LABELS,
    NUTZUNG_GEMISCHT,
    NUTZUNG_WOHNEN,
    PEGEL_UNTER_KONTUR,
)

# Bodenrichtwert-Stichtag -> Kalenderjahr der Lärmkonturen (Vorjahr).
# Für 2026 sind die 2025er Konturen noch nicht veröffentlicht; ersatzweise
# wird 2024 verwendet. Das ist in der Dokumentation als Limitation vermerkt.
REFERENZ_STICHTAG = 2024

STICHTAG_ZU_LAERMJAHR = {2020: 2019, 2022: 2021, 2024: 2023, 2026: 2024}

WGFZ_COL = "wertrelevanteGeschossflaechenzahl|BR_WertOderWertespanneDezimalzahl|wert"
GEMARKUNG_COL = "gemarkung|BR_Gemarkung|name"


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def load_reference_zones() -> gpd.GeoDataFrame:
    """Zonen des Stichtags 2024 als Referenzgeometrie."""
    g = gpd.read_parquet(DATA_RAW / "boris_2024.parquet").to_crs(CRS_METRIC)
    # "gemeinde" ist im Quellschema die Schlüsselziffer, "name" der Klarname
    g = g.rename(columns={"gemeinde": "gemeinde_ags"})
    g["ags"] = (
        g["land"].astype(str).str.zfill(2)
        + g["regierungsbezirk"].astype(str)
        + g["kreis"].astype(str).str.zfill(2)
        + g["gemeinde_ags"].astype(str).str.zfill(3)
    )
    g = g.rename(
        columns={
            "name": "gemeinde",
            GEMARKUNG_COL: "gemarkung",
            WGFZ_COL: "wgfz",
            "ortsteilName": "ortsteil",
            "postleitzahl": "plz",
        }
    )
    keep = [
        "gml_id", "gemeinde", "ags", "gemarkung", "ortsteil", "plz",
        "bodenrichtwertNummer", "entwicklungszustand", "art", "ergaenzung",
        "wgfz", "bauweise", "geometry",
    ]
    g = g[[c for c in keep if c in g.columns]].copy()
    g["wgfz"] = _num(g["wgfz"])
    g["flaeche_m2"] = g.geometry.area
    return g


def brw_at_points(year: int, points: gpd.GeoSeries) -> pd.DataFrame:
    """Bodenrichtwert eines Stichtags an vorgegebenen Punkten auslesen.

    Zurückgegeben wird neben dem Wert auch die Nutzungsklasse des getroffenen
    Zuschnitts. Sie wird gebraucht, weil sich die Zonengrenzen zwischen den
    Stichtagen verschieben: Ein Punkt, der 2024 in einer Wohnbauzone lag, kann
    2026 in einer aufgeteilten Landwirtschaftsfläche liegen. Ohne Prüfung
    entstünden Scheinänderungen von mehreren tausend Prozent (Ackerland zu
    0,70 EUR/m² gegen Bauland zu 350 EUR/m²).
    """
    if year == 2026:
        df = gpd.read_parquet(DATA_RAW / "boris_2026.parquet")
        out = pd.DataFrame(
            {
                "bodenrichtwert": df["bodenrichtwert"].values,
                "ist_bauland": df["entwicklungszustand_txt"].eq("Baureifes Land").values,
                "ist_wohnen": df["nutzung_txt"]
                .fillna("")
                .str.lower()
                .str.contains("wohn")
                .values,
            },
            index=df["gml_id_2024"].values,
        )
        return out

    zones = gpd.read_parquet(DATA_RAW / f"boris_{year}.parquet").to_crs(CRS_METRIC)
    zones = zones[["bodenrichtwert", "art", "entwicklungszustand", "geometry"]].copy()
    zones["bodenrichtwert"] = _num(zones["bodenrichtwert"])

    if year == REFERENZ_STICHTAG:
        # Referenzjahr: Werte direkt übernehmen. Ein räumlicher Rückverschnitt
        # auf die eigenen Zonen träfe bei überlappenden Zuschnitten teils die
        # falsche Zone.
        return pd.DataFrame(
            {
                "bodenrichtwert": zones["bodenrichtwert"].values,
                "ist_bauland": zones["entwicklungszustand"].eq("B").values,
                "ist_wohnen": zones["art"].isin(NUTZUNG_WOHNEN).values,
            }
        )

    pts = gpd.GeoDataFrame(geometry=points, crs=CRS_METRIC).reset_index(drop=True)
    joined = gpd.sjoin(pts, zones, how="left", predicate="within")
    joined = joined[~joined.index.duplicated(keep="first")]

    return pd.DataFrame(
        {
            "bodenrichtwert": joined["bodenrichtwert"].values,
            "ist_bauland": joined["entwicklungszustand"].eq("B").values,
            "ist_wohnen": joined["art"].isin(NUTZUNG_WOHNEN).values,
        }
    )


def noise_at_points(jahr: int, zeitraum: str, points: gpd.GeoSeries) -> pd.Series:
    """Pegel aus den verschachtelten Isophonen: Maximum aller Treffer."""
    path = DATA_RAW / f"konturen_{jahr}_{zeitraum}.parquet"
    contours = gpd.read_parquet(path).to_crs(CRS_METRIC)[["pegel", "geometry"]]

    pts = gpd.GeoDataFrame(geometry=points, crs=CRS_METRIC).reset_index(drop=True)
    pts["_i"] = pts.index
    joined = gpd.sjoin(pts, contours, how="left", predicate="within")
    return joined.groupby("_i")["pegel"].max()


def main() -> None:
    ref = load_reference_zones()
    pts = ref.geometry.representative_point()
    print(f"Referenz: {len(ref)} Zonen (Stichtag 2024)")

    # --- Kontrollvariablen -------------------------------------------
    kontrollen = pd.read_parquet(DATA_RAW / "kontrollen_zonen.parquet")
    ref = ref.merge(kontrollen, on="gml_id", how="left")

    # EU-Umgebungslärmkartierung 2022 als Zweitquelle (u. a. Straßenlärm)
    eu_laerm = pd.read_parquet(DATA_RAW / "laerm_zonen.parquet")
    ref = ref.merge(
        eu_laerm[["gml_id", "strasse_lden", "strasse_lnight", "schiene_lden", "industrie_lden"]],
        on="gml_id", how="left",
    )

    # --- Panel über die Stichtage ------------------------------------
    stichtage = [y for y in STICHTAG_ZU_LAERMJAHR if (DATA_RAW / f"boris_{y}.parquet").exists()]
    print(f"Stichtage im Panel: {stichtage}")

    # Nutzungsklasse der Referenzzonen, gegen die abgeglichen wird
    ref_wohnbauland = ref["art"].isin(NUTZUNG_WOHNEN) & ref["entwicklungszustand"].eq("B")

    frames = []
    for year in stichtage:
        laermjahr = STICHTAG_ZU_LAERMJAHR[year]
        treffer = brw_at_points(year, pts)
        if year == 2026:
            treffer = treffer.reindex(ref["gml_id"].values).reset_index(drop=True)

        werte = pd.to_numeric(treffer["bodenrichtwert"], errors="coerce")

        # Verwerfen, wenn der getroffene Zuschnitt eine andere Nutzung hat als
        # die Referenzzone -- sonst vergleicht das Panel Äpfel mit Birnen.
        passend = ~(
            ref_wohnbauland.values
            & ~(treffer["ist_bauland"].fillna(False) & treffer["ist_wohnen"].fillna(False))
        )
        verworfen = int((~passend & ref_wohnbauland.values).sum())
        werte = werte.where(passend)

        frame = pd.DataFrame(
            {
                "gml_id": ref["gml_id"].values,
                "stichtag": year,
                "laermjahr": laermjahr,
                "bodenrichtwert": werte.values,
                "flug_tag": noise_at_points(laermjahr, "tag", pts).reindex(ref.index).values,
                "flug_nacht": noise_at_points(laermjahr, "nacht", pts).reindex(ref.index).values,
            }
        )
        n_ok = frame["bodenrichtwert"].notna().sum()
        n_laerm = frame["flug_tag"].notna().sum()
        print(
            f"  {year}: {n_ok} Werte zugeordnet, {n_laerm} Zonen mit Fluglärmpegel"
            f", {verworfen} wegen abweichender Nutzung verworfen"
        )
        frames.append(frame)

    panel = pd.concat(frames, ignore_index=True)

    # --- Ableitungen --------------------------------------------------
    # Zonen ohne Isophonentreffer liegen unterhalb der niedrigsten Kontur
    # (48 dB(A) tags). Sie bekommen einen Ersatzwert, damit sie als "leise"
    # in die Modelle eingehen statt zu fehlen, und bilden die Referenzgruppe.
    panel["flug_tag_gefuellt"] = panel["flug_tag"].fillna(PEGEL_UNTER_KONTUR)
    panel["unter_kontur"] = panel["flug_tag"].isna()

    panel["log_brw"] = np.log(panel["bodenrichtwert"].where(panel["bodenrichtwert"] > 0))
    panel["laermklasse"] = pd.cut(
        panel["flug_tag_gefuellt"], bins=LDEN_BINS, labels=LDEN_LABELS, right=False
    )

    ref_out = ref.copy()
    ref_out["nutzung_gruppe"] = np.where(
        ref_out["art"].isin(NUTZUNG_WOHNEN),
        "wohnen",
        np.where(ref_out["art"].isin(NUTZUNG_GEMISCHT), "gemischt", "sonstige"),
    )
    ref_out["ist_bauland"] = ref_out["entwicklungszustand"] == "B"
    ref_out["dist_flughafen_km"] = ref_out["dist_flughafen_m"] / 1000
    ref_out["dist_bahn_km"] = ref_out["dist_bahn_m"] / 1000
    ref_out["dist_autobahn_km"] = ref_out["dist_autobahn_m"] / 1000
    ref_out["dist_zentrum_km"] = ref_out["dist_naechstes_zentrum_m"] / 1000
    ref_out["anteil_industrie_1km"] = ref_out["anteil_industrie_1km"].fillna(0.0)
    ref_out["anteil_gruen_1km"] = ref_out["anteil_gruen_1km"].fillna(0.0)

    ref_out.to_parquet(DATA_PROCESSED / "zonen.parquet")
    panel.to_parquet(DATA_PROCESSED / "panel.parquet")

    # --- Kurzdiagnose --------------------------------------------------
    wohn = ref_out[(ref_out["nutzung_gruppe"] == "wohnen") & ref_out["ist_bauland"]]
    print(f"\nWohnbauflächen (baureifes Land): {len(wohn)} Zonen")
    p24 = panel[panel["stichtag"] == 2024].set_index("gml_id")
    p24 = p24.loc[p24.index.intersection(wohn["gml_id"])]
    print(f"  davon mit Fluglärmpegel: {p24['flug_tag'].notna().sum()}")
    print(f"  Pegelbereich: {p24['flug_tag'].min():.0f} - {p24['flug_tag'].max():.0f} dB(A)")
    print(f"\n-> {DATA_PROCESSED / 'panel.parquet'} ({len(panel)} Zeilen)")


if __name__ == "__main__":
    main()

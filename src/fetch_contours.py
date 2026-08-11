"""Jährliche Fluglärmkonturen des Umwelt- und Nachbarschaftshauses (UNH).

Das UNH veröffentlicht für den Frankfurter Flughafen Isophonenkarten je
Kalenderjahr -- als Vektorpolygone und, anders als die EU-Kartierung, schon
ab ~43 dB(A) statt erst ab 55 dB. Dadurch entsteht ein echtes Panel: der
Lärm variiert innerhalb ein und derselben Zone über die Jahre (u. a. durch
den Verkehrseinbruch 2020/21 und die anschließende Erholung).

Die Konturen sind kumulativ verschachtelt: jedes Polygon umfasst die Fläche
mit Pegel >= X dB(A). Der Pegel an einem Punkt ist deshalb das Maximum der
Pegel aller Polygone, die ihn enthalten.

Ergebnis: data/raw/konturen_<jahr>_<tag|nacht>.parquet
"""

from __future__ import annotations

import json
import time
import urllib.parse

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import MultiPolygon, Polygon

from config import CRS_METRIC, DATA_RAW, REQUEST_DELAY_S, USER_AGENT

SERVICE = (
    "https://services-eu1.arcgis.com/DKU6cXKvWZEnO3Hr/arcgis/rest/services/"
    + urllib.parse.quote("Fluglärmkonturen")
    + "/FeatureServer"
)

# Layer-IDs: 0 = LAeq TAG 2007, 1 = LAeq NACHT 2007, danach je Jahr +2.
FIRST_YEAR = 2007
LAST_YEAR = 2024

# Für die Analyse relevante Jahre: Bodenrichtwert-Stichtag 01.01.JJJJ spiegelt
# die Lärmerfahrung des Vorjahres, deshalb 2019/2021/2023 (+ 2024 als bester
# verfügbarer Stand für den Stichtag 2026).
YEARS = tuple(range(2013, LAST_YEAR + 1))

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT})


def _layer_id(year: int, nacht: bool) -> int:
    return (year - FIRST_YEAR) * 2 + (1 if nacht else 0)


def _rings_to_polygon(rings: list[list[list[float]]]) -> Polygon | MultiPolygon:
    """Esri-Ringe in Shapely-Geometrie übersetzen.

    Esri unterscheidet Außen- und Innenringe über die Umlaufrichtung:
    im Uhrzeigersinn = Außenring, gegen den Uhrzeigersinn = Loch.
    """

    def signed_area(ring: list[list[float]]) -> float:
        return sum(
            (ring[i][0] * ring[i + 1][1]) - (ring[i + 1][0] * ring[i][1])
            for i in range(len(ring) - 1)
        ) / 2.0

    outers: list[list] = []
    holes: list[list] = []
    for ring in rings:
        (outers if signed_area(ring) < 0 else holes).append(ring)

    if not outers:  # defensiv: alles als Außenring behandeln
        outers, holes = rings, []

    polys = []
    for outer in outers:
        shell = Polygon(outer)
        inner = [h for h in holes if shell.contains(Polygon(h).representative_point())]
        polys.append(Polygon(outer, inner))

    return polys[0] if len(polys) == 1 else MultiPolygon(polys)


def fetch_layer(year: int, nacht: bool) -> gpd.GeoDataFrame:
    lid = _layer_id(year, nacht)
    params = {
        "where": "1=1",
        "outFields": "Pegelbereich,Pegel_Punkt,Isophonenflaeche",
        "returnGeometry": "true",
        "outSR": "25832",
        "f": "json",
    }
    resp = SESSION.get(f"{SERVICE}/{lid}/query", params=params, timeout=180)
    resp.raise_for_status()
    data = resp.json()

    if "features" not in data:
        raise RuntimeError(f"Layer {lid} ({year}): unerwartete Antwort {json.dumps(data)[:200]}")

    rows = []
    for feat in data["features"]:
        attrs = feat["attributes"]
        pegel_txt = (attrs.get("Pegel_Punkt") or "").split()[0]
        try:
            pegel = float(pegel_txt)
        except ValueError:
            continue
        rows.append(
            {
                "jahr": year,
                "zeitraum": "nacht" if nacht else "tag",
                "pegel": pegel,
                "pegelbereich": attrs.get("Pegelbereich"),
                "geometry": _rings_to_polygon(feat["geometry"]["rings"]),
            }
        )

    gdf = gpd.GeoDataFrame(rows, crs=CRS_METRIC)
    gdf["geometry"] = gdf.geometry.buffer(0)  # topologische Selbstschnitte glätten
    return gdf


def main() -> None:
    for year in YEARS:
        for nacht in (False, True):
            label = "nacht" if nacht else "tag"
            out = DATA_RAW / f"konturen_{year}_{label}.parquet"
            if out.exists():
                continue
            gdf = fetch_layer(year, nacht)
            gdf.to_parquet(out)
            print(
                f"  {year} {label:5s}: {len(gdf):2d} Isophonen, "
                f"{gdf['pegel'].min():.0f}-{gdf['pegel'].max():.0f} dB(A)"
            )
            time.sleep(REQUEST_DELAY_S)
    print("Fertig.")


if __name__ == "__main__":
    main()

"""Sozialstruktur aus dem Zensus 2022 als Kontrollvariablen.

Der größte verbleibende Störfaktor der Analyse: Die Fluglärmgemeinden im
Rhein-Main-Gebiet sind historisch Arbeiter- und Industriestädte. Ihre
Bodenwerte sind auch unabhängig vom Lärm niedriger -- wegen Sozialstruktur,
Baualter und Wohnungsbestand. Ohne diese Kontrollen schreibt das Modell dem
Lärm zu, was eigentlich Stadtgeschichte ist.

Bezogen wird das 1-km-Gitter des Zensus 2022 über den ArcGIS-FeatureServer
des Statistischen Bundesamts. Das 100-m-Gitter wäre feiner, ist aber in weiten
Teilen aus Geheimhaltungsgründen leer.

Ergebnis: data/raw/zensus_gitter.parquet
"""

from __future__ import annotations

import json
import time

import geopandas as gpd
import pandas as pd
import requests

from config import CRS_METRIC, DATA_RAW, REQUEST_DELAY_S, STUDY_BBOX_25832, USER_AGENT

SERVICE = (
    "https://services2.arcgis.com/jUpNdisbWqRpMo35/arcgis/rest/services/"
    "Zensus2022_grid_final/FeatureServer/1"
)

# Vorbestimmte Strukturmerkmale, die als Kontrollen taugen.
FELDER_KONTROLLE = [
    "GITTER_ID_1km",
    "Einwohner",
    "Durchschnittsalter",
    "DurchschnHHGroesse",
    "Eigentuemerquote",
    "AnteilAuslaender",
    "AnteilUeber65",
    "durchschnFlaechejeWohn",
    "Insgesamt_Gebaeude",
    "Vor1919",
    "a1919bis1948",
    "a1949bis1978",
    "a1979bis1990",
    "a1991bis2000",
]

# Die Nettokaltmiete wird mitgeführt, aber NICHT als Kontrolle verwendet:
# Sie ist selbst ein Preis und reagiert auf Lärm. Als Kontrolle würde sie
# genau den Effekt aufsaugen, der gemessen werden soll. Sie dient stattdessen
# als alternative Zielgröße.
FELDER_ZIEL = ["durchschnMieteQM", "Leerstandsquote"]

SEITE = 2000

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT})


def _abfrage(offset: int) -> dict:
    minx, miny, maxx, maxy = STUDY_BBOX_25832
    geom = {
        "xmin": minx, "ymin": miny, "xmax": maxx, "ymax": maxy,
        "spatialReference": {"wkid": 25832},
    }
    params = {
        "geometry": json.dumps(geom),
        "geometryType": "esriGeometryEnvelope",
        "inSR": "25832",
        "outSR": "25832",
        "spatialRel": "esriSpatialRelIntersects",
        "where": "1=1",
        "outFields": ",".join(FELDER_KONTROLLE + FELDER_ZIEL),
        "returnGeometry": "true",
        "resultOffset": offset,
        "resultRecordCount": SEITE,
        "f": "json",
    }
    resp = SESSION.get(f"{SERVICE}/query", params=params, timeout=180)
    resp.raise_for_status()
    return resp.json()


def hole_gitter() -> gpd.GeoDataFrame:
    zeilen = []
    offset = 0
    while True:
        antwort = _abfrage(offset)
        features = antwort.get("features", [])
        if not features:
            break

        for f in features:
            attrs = dict(f["attributes"])
            ring = f["geometry"]["rings"][0]
            xs = [p[0] for p in ring]
            ys = [p[1] for p in ring]
            attrs["mitte_x"] = (min(xs) + max(xs)) / 2
            attrs["mitte_y"] = (min(ys) + max(ys)) / 2
            zeilen.append(attrs)

        print(f"  {len(zeilen)} Gitterzellen geladen")
        if not antwort.get("exceededTransferLimit"):
            break
        offset += SEITE
        time.sleep(REQUEST_DELAY_S)

    df = pd.DataFrame(zeilen)
    return gpd.GeoDataFrame(
        df,
        geometry=gpd.points_from_xy(df["mitte_x"], df["mitte_y"]),
        crs=CRS_METRIC,
    )


def leite_ab(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Aus den Rohzählungen vergleichbare Anteile bilden."""
    gebaeude = gdf["Insgesamt_Gebaeude"].replace(0, pd.NA)

    gdf["anteil_altbau_vor1949"] = (
        (gdf["Vor1919"].fillna(0) + gdf["a1919bis1948"].fillna(0)) / gebaeude
    )
    gdf["anteil_nachkriegsbau"] = (
        (gdf["a1949bis1978"].fillna(0) + gdf["a1979bis1990"].fillna(0)) / gebaeude
    )
    gdf["einwohner_je_km2"] = gdf["Einwohner"]
    return gdf


def main() -> None:
    ziel = DATA_RAW / "zensus_gitter.parquet"
    if ziel.exists():
        print("zensus_gitter.parquet existiert bereits -> übersprungen")
        return

    print("Zensus-2022-Gitter (1 km) für das Untersuchungsgebiet abrufen ...")
    gdf = leite_ab(hole_gitter())
    gdf.to_parquet(ziel)

    print(f"-> {ziel.name}: {len(gdf)} Zellen")
    besetzt = gdf[gdf["Einwohner"].fillna(0) > 0]
    print(f"   davon bewohnt: {len(besetzt)}")
    for spalte in ("Einwohner", "Eigentuemerquote", "AnteilAuslaender", "durchschnMieteQM"):
        s = besetzt[spalte].dropna()
        if len(s):
            print(f"   {spalte:22s} Median {s.median():8.1f}  ({len(s)} Zellen)")


if __name__ == "__main__":
    main()

"""Bodenrichtwerte Rheinland-Pfalz (Mainz) über den freien VBORIS-Dienst.

Vorgeschichte: Der Versuch, BORIS RLP über die OGC-API-Features unter
geoportal.rlp.de/spatial-objects/548 abzurufen, scheiterte an HTTP 401 --
Registrierung allein schaltet geschützte Dienste dort nicht frei, das muss
der Datenanbieter (LVermGeo) von Hand tun.

Es gibt aber einen zweiten, tatsächlich offenen Weg: den kostenfreien
"VBORIS RLP Basisdienst" als WMS unter geo5.service24.rlp.de. Er liefert
zwar nur Kartenbilder, unterstützt aber GetFeatureInfo -- an einem
angeklickten Punkt liest der Dienst Zonennummer, Bodenrichtwert,
Entwicklungszustand und Nutzungsart aus, exakt wie der Basisdienst-Viewer
das im Browser tut. Kein Konto nötig.

Da es sich um einen WMS und keinen WFS handelt, gibt es keine
Zonenpolygone -- nur Werte an angefragten Punkten. Abgefragt wird deshalb
ein Punktraster über Mainz, und jeder Punkt wird als quadratische Kachel in
Rastergröße gezeichnet. Das ist methodisch etwas anderes als die
Zonenpolygone aus Hessen (weshalb diese Kacheln NICHT in die
Regressionsmodelle einfließen, siehe README), ergibt aber genau das
Kachelsystem, das für die Karte ursprünglich vorgeschwebt hat.

Ergebnis: data/raw/boris_rlp_tiles_<jahr>.parquet
"""

from __future__ import annotations

import re
import time
from html import unescape

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
from shapely.geometry import box

from config import CRS_METRIC, DATA_RAW, REQUEST_DELAY_S, USER_AGENT

WMS_TEMPLATE = "https://geo5.service24.rlp.de/wms/RLP_VBORISFREE{jahr}.fcgi"
LAYER = "Bodenrichtwerte_Basis_RLP"
STICHTAGE = (2024, 2026)

# Mainz-Stadtgebiet in EPSG:25832 -- deckt die durch "Cindy S" entlastete
# Südumfliegung ab. Größer als nötig zu fassen lohnt kaum: außerhalb des
# Stadtgebiets gehört die Fläche meist zu anderen Gutachterausschüssen mit
# eigenen, ebenfalls abzufragenden Diensten.
MAINZ_BBOX_25832 = (442_000, 5_533_000, 452_500, 5_544_000)
RASTER_M = 450

_ZELLE_MUSTER = re.compile(r"<td[^>]*>(.*?)</td>", re.IGNORECASE | re.DOTALL)
_TAG_MUSTER = re.compile(r"<[^>]+>")

FELDER = {
    "Nummer der Bodenrichtwertzone": "zone_nr",
    "Bodenrichtwert": "brw_roh",
    "Entwicklungszustand": "entwicklungszustand",
    "Nutzungsart": "art",
    "Gemeinde": "gemeinde",
    "Gemarkung": "gemarkung",
}

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT})


def _raster_punkte() -> list[tuple[float, float]]:
    minx, miny, maxx, maxy = MAINZ_BBOX_25832
    xs = np.arange(minx + RASTER_M / 2, maxx, RASTER_M)
    ys = np.arange(miny + RASTER_M / 2, maxy, RASTER_M)
    return [(x, y) for x in xs for y in ys]


def _parse_feature_info(html: str) -> dict | None:
    zellen = [unescape(_TAG_MUSTER.sub("", z)).strip() for z in _ZELLE_MUSTER.findall(html)]
    zellen = [z for z in zellen if z]

    treffer = {}
    for i, zelle in enumerate(zellen[:-1]):
        for label, feld in FELDER.items():
            if zelle == label:
                treffer[feld] = zellen[i + 1]
                break

    if "brw_roh" not in treffer:
        return None

    zahl = re.search(r"[\d.,]+", treffer["brw_roh"])
    if not zahl:
        return None
    treffer["bodenrichtwert"] = float(zahl.group(0).replace(".", "").replace(",", "."))
    return treffer


def _abfragen(jahr: int, x: float, y: float) -> dict | None:
    resp = SESSION.get(
        WMS_TEMPLATE.format(jahr=jahr),
        params={
            "SERVICE": "WMS", "VERSION": "1.1.1", "REQUEST": "GetFeatureInfo",
            "LAYERS": LAYER, "QUERY_LAYERS": LAYER, "STYLES": "",
            "SRS": CRS_METRIC,
            "BBOX": f"{x-500},{y-500},{x+500},{y+500}",
            "WIDTH": 400, "HEIGHT": 400, "X": 200, "Y": 200,
            "INFO_FORMAT": "text/html", "FEATURE_COUNT": 1,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return _parse_feature_info(resp.text)


def hole_stichtag(jahr: int) -> gpd.GeoDataFrame:
    punkte = _raster_punkte()
    zeilen = []
    for i, (x, y) in enumerate(punkte):
        try:
            treffer = _abfragen(jahr, x, y)
        except requests.RequestException:
            treffer = None
        if treffer:
            treffer["geometry"] = box(
                x - RASTER_M / 2, y - RASTER_M / 2, x + RASTER_M / 2, y + RASTER_M / 2
            )
            zeilen.append(treffer)
        if (i + 1) % 100 == 0:
            print(f"  [{jahr}] {i+1}/{len(punkte)} Punkte abgefragt, {len(zeilen)} Treffer")
        time.sleep(REQUEST_DELAY_S)

    return gpd.GeoDataFrame(zeilen, geometry="geometry", crs=CRS_METRIC)


def main() -> None:
    for jahr in STICHTAGE:
        ziel = DATA_RAW / f"boris_rlp_tiles_{jahr}.parquet"
        if ziel.exists():
            print(f"[{jahr}] existiert bereits -> übersprungen")
            continue
        print(f"[{jahr}] Raster über Mainz abfragen ({len(_raster_punkte())} Punkte) ...")
        gdf = hole_stichtag(jahr)
        gdf.to_parquet(ziel)
        print(f"[{jahr}] {len(gdf)} Kacheln mit Bodenrichtwert -> {ziel.name}")


if __name__ == "__main__":
    main()

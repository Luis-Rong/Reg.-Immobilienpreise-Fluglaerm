"""Bodenrichtwerte Rheinland-Pfalz -- für Mainz und die entlastete Westseite.

Stand der Prüfung (August 2026): Die Daten existieren und wären fachlich ein
Gewinn -- Rheinland-Pfalz führt Stichtage von 2000 bis 2026 und damit eine
längere Reihe als Hessen. Automatisiert abrufbar sind sie aber nicht:

* OGC API Features unter geoportal.rlp.de/spatial-objects/548 antwortet mit
  HTTP 401; die Sammlungen (ms:BORIS_2000 ... ms:BORIS_2026) sind zwar
  auflistbar, die Features selbst nicht.
* Die Dienste unter geo5.service24.rlp.de antworten durchgängig mit HTTP 403.
* Auf der Open-Data-Seite des LVermGeo steht kein Massendownload bereit.

Der kostenfreie "Basisdienst" ist nur interaktiv über boris.rlp.de nutzbar.
Für den automatisierten Zugriff ist eine Registrierung beim GeoPortal.rlp
nötig -- die muss der Betreiber des Projekts selbst vornehmen, Zugangsdaten
gehören nicht in ein öffentliches Repository.

Sobald ein Zugang besteht, genügt es, die beiden Umgebungsvariablen zu setzen:

    set RLP_GEOPORTAL_USER=...
    set RLP_GEOPORTAL_PASS=...

Danach lädt dieses Skript die Zonen analog zu fetch_boris.py.

Ergebnis: data/raw/boris_rlp_<jahr>.parquet
"""

from __future__ import annotations

import os
import sys

import geopandas as gpd
import requests
from requests.auth import HTTPBasicAuth

from config import CRS_WGS84, DATA_RAW, STUDY_BBOX_25832, USER_AGENT

API = "https://www.geoportal.rlp.de/spatial-objects/548"
STICHTAGE = (2020, 2022, 2024, 2026)

# Der Dienst akzeptiert nur diese Werte für limit.
SEITE = 1000


def _bbox_wgs84() -> str:
    minx, miny, maxx, maxy = STUDY_BBOX_25832
    ecken = gpd.GeoSeries(
        gpd.points_from_xy([minx, maxx], [miny, maxy]), crs="EPSG:25832"
    ).to_crs(CRS_WGS84)
    return f"{ecken.iloc[0].x},{ecken.iloc[0].y},{ecken.iloc[1].x},{ecken.iloc[1].y}"


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    nutzer, passwort = os.getenv("RLP_GEOPORTAL_USER"), os.getenv("RLP_GEOPORTAL_PASS")
    if nutzer and passwort:
        s.auth = HTTPBasicAuth(nutzer, passwort)
    return s


def hole_stichtag(session: requests.Session, jahr: int) -> gpd.GeoDataFrame:
    features = []
    offset = 0
    while True:
        antwort = session.get(
            f"{API}/collections/ms:BORIS_{jahr}/items",
            params={"bbox": _bbox_wgs84(), "limit": SEITE, "offset": offset, "f": "json"},
            timeout=180,
        )
        antwort.raise_for_status()
        daten = antwort.json()
        teil = daten.get("features", [])
        features.extend(teil)
        if len(teil) < SEITE:
            break
        offset += SEITE

    return gpd.GeoDataFrame.from_features(features, crs=CRS_WGS84)


def main() -> None:
    session = _session()
    if session.auth is None:
        print(
            "Keine Zugangsdaten gefunden.\n\n"
            "Der BORIS-Dienst von Rheinland-Pfalz ist nicht frei abrufbar: die\n"
            "OGC-API antwortet mit HTTP 401, die Dienste unter\n"
            "geo5.service24.rlp.de mit HTTP 403, und einen Massendownload gibt\n"
            "es nicht. Für Hessen war das anders -- dort sind sowohl WFS als\n"
            "auch WMS ohne Anmeldung nutzbar.\n\n"
            "Zum Freischalten: beim GeoPortal.rlp registrieren und danach\n"
            "RLP_GEOPORTAL_USER und RLP_GEOPORTAL_PASS setzen.\n\n"
            "Ohne Mainz fehlt der Analyse die durch 'Cindy S' entlastete\n"
            "Westseite; vertreten ist sie derzeit nur durch Wiesbaden."
        )
        sys.exit(1)

    for jahr in STICHTAGE:
        ziel = DATA_RAW / f"boris_rlp_{jahr}.parquet"
        if ziel.exists():
            print(f"[{jahr}] existiert bereits -> übersprungen")
            continue
        gdf = hole_stichtag(session, jahr)
        gdf.to_parquet(ziel)
        print(f"[{jahr}] {len(gdf)} Zonen -> {ziel.name}")


if __name__ == "__main__":
    main()

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

Wichtig: Eine Registrierung beim GeoPortal.rlp allein genügt NICHT. Geschützte
Dienste müssen vom Datenanbieter -- hier dem LVermGeo -- für das jeweilige
Konto einzeln freigeschaltet werden. Der Antrag läuft über das Geoportal, der
Anbieter entscheidet darüber von Hand. Mit registriertem, aber nicht
freigeschaltetem Konto antwortet der Dienst weiterhin mit HTTP 401.

Sobald ein Zugang besteht, gehören die Zugangsdaten in die Datei .env im
Projektverzeichnis (Vorlage: .env.beispiel). Sie wird von git ignoriert:

    RLP_GEOPORTAL_USER=...
    RLP_GEOPORTAL_PASS=...

Alternativ funktionieren gleichnamige Umgebungsvariablen. Beides gehört
niemals in den Quelltext -- der landet im öffentlichen Repository.

Ergebnis: data/raw/boris_rlp_<jahr>.parquet
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

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


def _lade_env() -> None:
    """Zugangsdaten aus der lokalen .env in die Umgebung übernehmen.

    Bewusst ohne Zusatzbibliothek: eine Zeile je Eintrag, Rauten sind
    Kommentare. Bereits gesetzte Umgebungsvariablen haben Vorrang.
    """
    pfad = Path(__file__).resolve().parent.parent / ".env"
    if not pfad.exists():
        return
    for zeile in pfad.read_text(encoding="utf-8").splitlines():
        zeile = zeile.strip()
        if not zeile or zeile.startswith("#") or "=" not in zeile:
            continue
        schluessel, wert = zeile.split("=", 1)
        os.environ.setdefault(schluessel.strip(), wert.strip())


def _session() -> requests.Session:
    _lade_env()
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
        try:
            gdf = hole_stichtag(session, jahr)
        except requests.HTTPError as fehler:
            if fehler.response is not None and fehler.response.status_code == 401:
                print(
                    f"[{jahr}] HTTP 401 trotz hinterlegter Zugangsdaten.\n\n"
                    "Das Konto ist offenbar registriert, aber für den "
                    "BORIS-Dienst noch nicht freigeschaltet. Geschützte Dienste\n"
                    "gibt im GeoPortal.rlp der Datenanbieter (LVermGeo) einzeln\n"
                    "frei; der Antrag läuft über das Portal und wird von Hand\n"
                    "bearbeitet. Bis dahin bleibt Mainz außen vor."
                )
                sys.exit(2)
            raise
        gdf.to_parquet(ziel)
        print(f"[{jahr}] {len(gdf)} Zonen -> {ziel.name}")


if __name__ == "__main__":
    main()

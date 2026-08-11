"""Bodenrichtwerte (BORIS Hessen) für das Untersuchungsgebiet beschaffen.

Zwei Wege, weil das Land die Stichtage unterschiedlich bereitstellt:

* 2020, 2022, 2024 -- WFS liefert Zonenpolygone samt Attributen im Bulk.
* 2026            -- kein WFS vorhanden (der /basis/-Endpunkt ist leer).
  Die Werte werden per WMS-GetFeatureInfo am Repräsentativpunkt jeder
  2024er-Zone abgefragt und auf diese Geometrie übertragen.

Beide Dienste sind nach § 1 Abs. 2 Gutachterausschusskostengesetz
kostenfrei nutzbar. Ergebnis: data/raw/boris_<jahr>.parquet
"""

from __future__ import annotations

import io
import re
import sys
import time
import warnings

import geopandas as gpd
import pandas as pd
import requests

from config import (
    BORIS_TYPENAME,
    BORIS_WFS_TEMPLATE,
    BORIS_WFS_YEARS,
    BORIS_WMS,
    BORIS_WMS_LAYER_2026,
    CRS_METRIC,
    DATA_RAW,
    REQUEST_DELAY_S,
    STUDY_BBOX_25832,
    USER_AGENT,
)

warnings.filterwarnings("ignore", message=".*Several features with id.*")

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT})

# Der Dienst antwortet zuverlässig bis ~1500 Features pro Anfrage; darüber
# bricht er ohne Fehlermeldung ab. Deshalb wird das Gebiet gekachelt.
TILE_SIZE_M = 9_000


def _tiles(bbox: tuple[float, float, float, float], step: float = TILE_SIZE_M):
    """Untersuchungsgebiet in Kacheln zerlegen, damit der WFS nicht abbricht."""
    minx, miny, maxx, maxy = bbox
    x = minx
    while x < maxx:
        y = miny
        while y < maxy:
            yield (x, y, min(x + step, maxx), min(y + step, maxy))
            y += step
        x += step


def fetch_wfs_year(year: int) -> gpd.GeoDataFrame:
    """Alle Bodenrichtwertzonen eines Stichtags per WFS holen."""
    url = BORIS_WFS_TEMPLATE.format(year=year)
    frames: list[gpd.GeoDataFrame] = []

    tiles = list(_tiles(STUDY_BBOX_25832))
    for i, (minx, miny, maxx, maxy) in enumerate(tiles, 1):
        params = {
            "SERVICE": "WFS",
            "VERSION": "2.0.0",
            "REQUEST": "GetFeature",
            "TYPENAMES": BORIS_TYPENAME,
            "SRSNAME": "urn:ogc:def:crs:EPSG::25832",
            "BBOX": f"{minx},{miny},{maxx},{maxy},urn:ogc:def:crs:EPSG::25832",
        }
        resp = SESSION.get(url, params=params, timeout=180)
        resp.raise_for_status()

        if b"<wfs:member>" not in resp.content:
            print(f"  [{year}] Kachel {i}/{len(tiles)}: leer")
            continue

        gdf = gpd.read_file(io.BytesIO(resp.content))
        frames.append(gdf)
        print(f"  [{year}] Kachel {i}/{len(tiles)}: {len(gdf)} Zonen")
        time.sleep(REQUEST_DELAY_S)

    if not frames:
        raise RuntimeError(f"WFS lieferte keine Daten für {year}")

    out = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=CRS_METRIC)
    # Kacheln überlappen an den Rändern nicht, aber Zonen können in zwei
    # Kacheln fallen, wenn sie die Grenze schneiden.
    out = out.drop_duplicates(subset="gml_id").reset_index(drop=True)
    return _normalise_dtypes(out)


def _normalise_dtypes(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Gemischte Objektspalten vereinheitlichen, sonst scheitert Parquet.

    Der WFS liefert Schlüsselfelder je nach Kachel mal als Zahl, mal als
    Zeichenkette (z. B. bodenrichtwertNummer).
    """
    for col in gdf.columns:
        if col == "geometry" or gdf[col].dtype != object:
            continue
        gdf[col] = gdf[col].map(lambda v: None if pd.isna(v) else str(v))
    return gdf


# --- 2026 über WMS-GetFeatureInfo ---------------------------------------

_BRW_PATTERN = re.compile(r"([^:;]+):\s*([\d.,]+)\s*EUR/m")


def _parse_gml_info(text: str) -> dict | None:
    """Ein GetFeatureInfo-GML-Dokument in ein flaches Dict übersetzen."""
    if "<hboris_feature_feature>" not in text:
        return None

    def tag(name: str) -> str | None:
        m = re.search(rf"<{name}>(.*?)</{name}>", text, re.S)
        return m.group(1).strip() if m else None

    brw_raw = tag("BRW") or ""
    # "Wohnbaufläche: 290 EUR/m²;landwirtschaftliche Fläche: 6,50 EUR/m²"
    werte = {
        art.strip().lower(): float(val.replace(".", "").replace(",", "."))
        for art, val in _BRW_PATTERN.findall(brw_raw)
    }
    wohn = next(
        (v for k, v in werte.items() if "wohn" in k),
        next(iter(werte.values()), None) if len(werte) == 1 else None,
    )

    return {
        "gemeinde_name": tag("GENA"),
        "gemeindeschluessel": tag("GESL"),
        "gemarkung_name": tag("GEMA"),
        "bodenrichtwertNummer": tag("WNUM"),
        "stichtag": tag("STAG"),
        "brw_roh": brw_raw,
        "bodenrichtwert": wohn,
        "entwicklungszustand_txt": tag("ENTW_KLART"),
        "nutzung_txt": tag("NUTA_KLART"),
        "wgfz_txt": tag("WGFZ"),
    }


def fetch_2026_at_points(zones_2024: gpd.GeoDataFrame) -> pd.DataFrame:
    """Stichtag 2026 punktweise am Repräsentativpunkt jeder Zone abfragen."""
    pts = zones_2024.geometry.representative_point()
    rows: list[dict] = []
    total = len(pts)
    half = 120.0  # halbe Kantenlänge der Abfrage-Box in Metern

    for i, pt in enumerate(pts, 1):
        params = {
            "language": "ger",
            "SERVICE": "WMS",
            "VERSION": "1.1.1",
            "REQUEST": "GetFeatureInfo",
            "LAYERS": BORIS_WMS_LAYER_2026,
            "QUERY_LAYERS": BORIS_WMS_LAYER_2026,
            "SRS": "EPSG:25832",
            "BBOX": f"{pt.x - half},{pt.y - half},{pt.x + half},{pt.y + half}",
            "WIDTH": 101,
            "HEIGHT": 101,
            "X": 50,
            "Y": 50,
            "INFO_FORMAT": "application/vnd.ogc.gml",
            "FEATURE_COUNT": 1,
        }
        try:
            resp = SESSION.get(BORIS_WMS, params=params, timeout=60)
            rec = _parse_gml_info(resp.text) if resp.ok else None
        except requests.RequestException as exc:
            print(f"  [2026] Punkt {i}: Fehler {exc}")
            rec = None

        if rec:
            rec["gml_id_2024"] = zones_2024.iloc[i - 1]["gml_id"]
            rows.append(rec)

        if i % 250 == 0 or i == total:
            print(f"  [2026] {i}/{total} Punkte abgefragt, {len(rows)} Treffer")
        time.sleep(REQUEST_DELAY_S)

    return pd.DataFrame(rows)


def main() -> None:
    only = sys.argv[1] if len(sys.argv) > 1 else None

    for year in BORIS_WFS_YEARS:
        if only and only != str(year):
            continue
        out_path = DATA_RAW / f"boris_{year}.parquet"
        if out_path.exists():
            print(f"[{year}] existiert bereits -> übersprungen")
            continue
        print(f"[{year}] WFS-Abruf ...")
        gdf = fetch_wfs_year(year)
        gdf.to_parquet(out_path)
        print(f"[{year}] {len(gdf)} Zonen -> {out_path.name}")

    if only and only != "2026":
        return

    out_2026 = DATA_RAW / "boris_2026.parquet"
    if out_2026.exists():
        print("[2026] existiert bereits -> übersprungen")
        return

    zones = gpd.read_parquet(DATA_RAW / "boris_2024.parquet")
    print(f"[2026] Punktabfrage an {len(zones)} Zonen-Repräsentativpunkten ...")
    df = fetch_2026_at_points(zones)

    # Geometrie der 2024er-Zone übernehmen (2026er Zuschnitte weichen nur
    # punktuell ab; das wird in der Dokumentation als Limitation genannt).
    geo = zones[["gml_id", "geometry"]].rename(columns={"gml_id": "gml_id_2024"})
    gdf = gpd.GeoDataFrame(df.merge(geo, on="gml_id_2024", how="left"), crs=CRS_METRIC)
    gdf.to_parquet(out_2026)
    print(f"[2026] {len(gdf)} Zonen -> {out_2026.name}")


if __name__ == "__main__":
    main()

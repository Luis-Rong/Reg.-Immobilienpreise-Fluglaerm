"""Standort-Kontrollvariablen aus OpenStreetMap.

Fluglärm ist räumlich mit Lagevorteilen konfundiert: Wer nah am Flughafen
wohnt, hat viel Lärm, aber auch kurze Wege zu Arbeitsplätzen, Autobahnen und
S-Bahn. Ohne diese Kontrollen misst der Lärmkoeffizient beides zugleich und
kann sogar positiv ausfallen.

Erhoben werden je Bodenrichtwertzone die Luftliniendistanzen zu
Schienenhaltepunkten, Autobahnanschlüssen, dem Flughafen selbst sowie den
nächstgelegenen Oberzentren.

Ergebnis: data/raw/kontrollen_zonen.parquet
"""

from __future__ import annotations

import time

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
from shapely.geometry import Point, Polygon

from config import (
    CRS_METRIC,
    CRS_WGS84,
    DATA_RAW,
    FRA_LAT,
    FRA_LON,
    STUDY_BBOX_25832,
    USER_AGENT,
)

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

# Oberzentren im und am Untersuchungsgebiet (Luftlinie zum jeweiligen Zentrum)
ZENTREN = {
    "frankfurt": (8.6821, 50.1109),  # Hauptwache
    "wiesbaden": (8.2417, 50.0826),
    "mainz": (8.2711, 49.9929),
    "darmstadt": (8.6512, 49.8728),
    "offenbach": (8.7595, 50.0955),
}

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT})


def _bbox_wgs84() -> tuple[float, float, float, float]:
    """Untersuchungsgebiet als (süd, west, nord, ost) für Overpass."""
    minx, miny, maxx, maxy = STUDY_BBOX_25832
    corners = gpd.GeoSeries(
        [Point(minx, miny), Point(maxx, maxy)], crs=CRS_METRIC
    ).to_crs(CRS_WGS84)
    # Etwas Puffer, damit auch knapp außerhalb liegende Bahnhöfe/Auffahrten
    # als nächstgelegene Einrichtung gefunden werden.
    return (
        corners.iloc[0].y - 0.1,
        corners.iloc[0].x - 0.1,
        corners.iloc[1].y + 0.1,
        corners.iloc[1].x + 0.1,
    )


def _overpass(query: str) -> dict:
    last_error: Exception | None = None
    for url in OVERPASS_ENDPOINTS:
        for attempt in range(3):
            try:
                resp = SESSION.post(url, data={"data": query}, timeout=300)
                if resp.status_code == 429 or resp.status_code == 504:
                    time.sleep(20 * (attempt + 1))
                    continue
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException as exc:
                last_error = exc
                time.sleep(10 * (attempt + 1))
    raise RuntimeError(f"Overpass nicht erreichbar: {last_error}")


def fetch_points(osm_filter: str, label: str) -> gpd.GeoDataFrame:
    """Punkt-Features aus OSM holen (Wege/Relationen über ihren Mittelpunkt)."""
    s, w, n, e = _bbox_wgs84()
    query = f"""
    [out:json][timeout:280];
    (
      node{osm_filter}({s},{w},{n},{e});
      way{osm_filter}({s},{w},{n},{e});
    );
    out center;
    """
    data = _overpass(query)
    rows = []
    for el in data.get("elements", []):
        lon = el.get("lon") or (el.get("center") or {}).get("lon")
        lat = el.get("lat") or (el.get("center") or {}).get("lat")
        if lon is None or lat is None:
            continue
        rows.append({"name": (el.get("tags") or {}).get("name"), "geometry": Point(lon, lat)})

    gdf = gpd.GeoDataFrame(rows, crs=CRS_WGS84).to_crs(CRS_METRIC)
    print(f"  {label}: {len(gdf)} Objekte")
    return gdf


def fetch_landuse(werte: list[str], label: str) -> gpd.GeoDataFrame:
    """Flächennutzungs-Polygone aus OSM holen."""
    s, w, n, e = _bbox_wgs84()
    regex = "|".join(werte)
    query = f"""
    [out:json][timeout:280];
    (
      way["landuse"~"^({regex})$"]({s},{w},{n},{e});
      relation["landuse"~"^({regex})$"]({s},{w},{n},{e});
    );
    out geom;
    """
    data = _overpass(query)
    polys = []
    for el in data.get("elements", []):
        coords = [(p["lon"], p["lat"]) for p in el.get("geometry", [])]
        if len(coords) >= 4:
            polys.append(Polygon(coords).buffer(0))
        for member in el.get("members", []):
            mc = [(p["lon"], p["lat"]) for p in member.get("geometry", [])]
            if len(mc) >= 4:
                polys.append(Polygon(mc).buffer(0))

    gdf = gpd.GeoDataFrame(geometry=polys, crs=CRS_WGS84).to_crs(CRS_METRIC)
    gdf = gdf[gdf.geometry.is_valid & ~gdf.geometry.is_empty]
    print(f"  {label}: {len(gdf)} Flächen")
    return gdf


def flaechenanteil(punkte: gpd.GeoSeries, flaechen: gpd.GeoDataFrame, radius: int) -> pd.Series:
    """Anteil einer Nutzungsart im Umkreis eines Punkts."""
    umkreis = gpd.GeoDataFrame(geometry=punkte.buffer(radius), crs=CRS_METRIC)
    umkreis["_i"] = range(len(umkreis))
    verschnitt = gpd.overlay(
        umkreis, gpd.GeoDataFrame(geometry=[flaechen.union_all()], crs=CRS_METRIC),
        how="intersection", keep_geom_type=True,
    )
    anteil = verschnitt.groupby("_i").geometry.apply(lambda g: g.area.sum())
    kreisflaeche = np.pi * radius**2
    return (anteil.reindex(range(len(umkreis))).fillna(0.0) / kreisflaeche).clip(0, 1)


def main() -> None:
    out_path = DATA_RAW / "kontrollen_zonen.parquet"
    if out_path.exists():
        print("kontrollen_zonen.parquet existiert bereits -> übersprungen")
        return

    zones = gpd.read_parquet(DATA_RAW / "boris_2024.parquet")
    pts = gpd.GeoDataFrame(
        {"gml_id": zones["gml_id"]},
        geometry=zones.geometry.representative_point(),
        crs=CRS_METRIC,
    )

    print("OSM-Abfragen ...")
    bahn = fetch_points('["railway"~"^(station|halt)$"]', "Schienenhaltepunkte")
    auffahrt = fetch_points('["highway"="motorway_junction"]', "Autobahnanschlüsse")

    out = pd.DataFrame({"gml_id": pts["gml_id"].values})

    for label, targets in (("bahn", bahn), ("autobahn", auffahrt)):
        joined = gpd.sjoin_nearest(
            pts[["gml_id", "geometry"]], targets[["geometry"]],
            how="left", distance_col=f"dist_{label}_m",
        ).drop_duplicates(subset="gml_id")
        out[f"dist_{label}_m"] = joined[f"dist_{label}_m"].values

    # Distanz zum Flughafen: Lagevorteil (Arbeitsplätze) und Lärmquelle zugleich
    fra = gpd.GeoSeries([Point(FRA_LON, FRA_LAT)], crs=CRS_WGS84).to_crs(CRS_METRIC).iloc[0]
    out["dist_flughafen_m"] = pts.geometry.distance(fra).values

    for name, (lon, lat) in ZENTREN.items():
        z = gpd.GeoSeries([Point(lon, lat)], crs=CRS_WGS84).to_crs(CRS_METRIC).iloc[0]
        out[f"dist_{name}_m"] = pts.geometry.distance(z).values

    zentren_cols = [f"dist_{n}_m" for n in ZENTREN]
    out["dist_naechstes_zentrum_m"] = out[zentren_cols].min(axis=1)

    # Industrienähe ist der wichtigste Störfaktor: die Fluglärmgemeinden im
    # Rhein-Main-Gebiet sind historisch auch Industriestandorte, was die
    # Bodenwerte unabhängig vom Lärm drückt.
    industrie = fetch_landuse(["industrial", "railway", "quarry"], "Industrieflächen")
    gruen = fetch_landuse(["forest", "meadow", "grass", "recreation_ground"], "Grünflächen")
    out["anteil_industrie_1km"] = flaechenanteil(pts.geometry, industrie, 1000).values
    out["anteil_gruen_1km"] = flaechenanteil(pts.geometry, gruen, 1000).values

    out.to_parquet(out_path)
    print(f"-> {out_path.name} ({len(out)} Zeilen, {len(out.columns)} Spalten)")


if __name__ == "__main__":
    main()

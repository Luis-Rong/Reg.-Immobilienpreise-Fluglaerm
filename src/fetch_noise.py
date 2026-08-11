"""Lärmbelastung je Bodenrichtwertzone aus der EU-Umgebungslärmkartierung 2022.

Das HLNUG stellt die Kartierung als Raster-Layer über einen ArcGIS-MapServer
bereit (kein WFS/Download-Dienst). Die Pegel werden deshalb per
identify-Operation am Repräsentativpunkt jeder Zone ausgelesen -- gebündelt
als Multipoint, dadurch ~1000 Punkte pro Anfrage statt einzeln.

Neben dem Fluglärm werden Straßen-, Schienen- und Industrielärm miterfasst;
sie dienen im Modell als Kontrollvariablen, damit der Fluglärmkoeffizient
nicht die allgemeine Lärmbelastung mit einsammelt.

Ergebnis: data/raw/laerm_zonen.parquet (eine Zeile je 2024er-Zone)
"""

from __future__ import annotations

import json
import time

import geopandas as gpd
import pandas as pd
import requests

from config import DATA_RAW, REQUEST_DELAY_S, USER_AGENT

MAPSERVER = (
    "https://geodienste-umwelt.hessen.de/arcgis/rest/services/"
    "laerm/laerm_oden/MapServer"
)

# Layer-IDs der Kartierung 2022 -> Spaltennamen im Ergebnis
NOISE_LAYERS = {
    6: "flug_lden",
    7: "flug_lnight",
    0: "strasse_lden",
    1: "strasse_lnight",
    2: "schiene_lden",
    5: "schiene_lnight",
    4: "industrie_lden",
    3: "industrie_lnight",
}

BATCH = 800

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT})


def _layer_extent(layer: int) -> tuple[float, float, float, float]:
    """Ausdehnung eines Rasterlayers abfragen."""
    resp = SESSION.get(f"{MAPSERVER}/{layer}", params={"f": "json"}, timeout=60)
    resp.raise_for_status()
    e = resp.json()["extent"]
    return e["xmin"], e["ymin"], e["xmax"], e["ymax"]


def _identify_batch(points: list[tuple[float, float]], layer: int) -> list[float | None]:
    """Rasterwerte für eine Punktliste abfragen; Reihenfolge bleibt erhalten.

    Wichtig: Punkte außerhalb der Rasterausdehnung lässt der Dienst
    kommentarlos weg, wodurch die Zuordnung Punkt->Ergebnis verrutschen
    würde. Deshalb wird vorher gefiltert (siehe fetch_noise_for_zones).
    """
    geom = {
        "points": [[x, y] for x, y in points],
        "spatialReference": {"wkid": 25832},
    }
    payload = {
        "geometry": json.dumps(geom),
        "geometryType": "esriGeometryMultipoint",
        "sr": "25832",
        "layers": f"all:{layer}",
        "tolerance": "1",
        # mapExtent/imageDisplay sind Pflichtfelder; bei tolerance=1 bestimmen
        # sie nur den Suchradius in Pixeln, nicht das Ergebnis.
        "mapExtent": "440000,5520000,494000,5562000",
        "imageDisplay": "1000,800,96",
        "returnGeometry": "false",
        "f": "json",
    }
    resp = SESSION.post(f"{MAPSERVER}/identify", data=payload, timeout=180)
    resp.raise_for_status()
    results = resp.json().get("results", [])

    if len(results) != len(points):
        raise RuntimeError(
            f"Layer {layer}: {len(results)} Ergebnisse für {len(points)} Punkte "
            "-- Zuordnung nicht mehr eindeutig"
        )

    values: list[float | None] = []
    for r in results:
        raw = r.get("attributes", {}).get("Classify.Pixelwert")
        try:
            values.append(float(raw))
        except (TypeError, ValueError):
            values.append(None)  # "NoData" = außerhalb der kartierten Fläche
    return values


def fetch_noise_for_zones(zones: gpd.GeoDataFrame) -> pd.DataFrame:
    pts_geom = zones.geometry.representative_point()
    points = [(p.x, p.y) for p in pts_geom]

    out = pd.DataFrame({"gml_id": zones["gml_id"].values})
    out["punkt_x"] = [p[0] for p in points]
    out["punkt_y"] = [p[1] for p in points]

    for layer, col in NOISE_LAYERS.items():
        xmin, ymin, xmax, ymax = _layer_extent(layer)
        inside = [
            i
            for i, (x, y) in enumerate(points)
            if xmin <= x <= xmax and ymin <= y <= ymax
        ]

        values: list[float | None] = [None] * len(points)
        for start in range(0, len(inside), BATCH):
            idx_chunk = inside[start : start + BATCH]
            chunk = [points[i] for i in idx_chunk]
            for i, val in zip(idx_chunk, _identify_batch(chunk, layer)):
                values[i] = val
            time.sleep(REQUEST_DELAY_S)

        out[col] = values
        n_hit = sum(v is not None for v in values)
        print(
            f"  Layer {layer:2d} -> {col:16s}: {n_hit:5d}/{len(values)} Punkte mit Pegel"
            f"  ({len(inside)} in Rasterausdehnung)"
        )

    return out


def main() -> None:
    out_path = DATA_RAW / "laerm_zonen.parquet"
    if out_path.exists():
        print("laerm_zonen.parquet existiert bereits -> übersprungen")
        return

    zones = gpd.read_parquet(DATA_RAW / "boris_2024.parquet")
    print(f"Lärmpegel für {len(zones)} Zonen abfragen ...")
    df = fetch_noise_for_zones(zones)
    df.to_parquet(out_path)
    print(f"-> {out_path.name} ({len(df)} Zeilen)")


if __name__ == "__main__":
    main()

"""Zentrale Konfiguration: Untersuchungsgebiet, Datenquellen, Treatment-Definitionen."""

from pathlib import Path

# --- Pfade ---------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DATA_RAW = ROOT / "data" / "raw"
DATA_PROCESSED = ROOT / "data" / "processed"
RESULTS = ROOT / "results"

for _p in (DATA_RAW, DATA_PROCESSED, RESULTS):
    _p.mkdir(parents=True, exist_ok=True)

# --- Koordinatensysteme --------------------------------------------------
CRS_METRIC = "EPSG:25832"  # ETRS89 / UTM 32N - amtliches System in Hessen
CRS_WGS84 = "EPSG:4326"

# --- Untersuchungsgebiet -------------------------------------------------
# Flughafen Frankfurt (Bezugspunkt, ARP)
FRA_LON, FRA_LAT = 8.570556, 50.033306

# Bounding Box in EPSG:25832: deckt die Ost-West-Anfluggrundlinie ab
# (Mainz/Wiesbaden im Westen bis Hanau im Osten) sowie die Süd-Achse bis
# Darmstadt (Cindy-S-Korridor) und den Taunusrand im Norden.
STUDY_BBOX_25832 = (440_000, 5_520_000, 494_000, 5_562_000)

# --- BORIS Bodenrichtwerte ----------------------------------------------
# WFS liefert Bulk-Vektordaten, aber nur bis Stichtag 2024.
BORIS_WFS_TEMPLATE = "https://www.gds.hessen.de/wfs2/boris/cgi-bin/brw/{year}/wfs"
BORIS_WFS_YEARS = (2020, 2022, 2024)
BORIS_TYPENAME = "boris:BR_BodenrichtwertZonal"

# Stichtag 2026 ist NICHT als WFS verfügbar (der /basis/-Endpunkt ist leer).
# Er wird über den WMS-Layer "hboris_feature" (= BORIS2026-Info) punktweise
# an den Zonen-Repräsentativpunkten von 2024 abgefragt.
BORIS_WMS = "https://www.gds-srv.hessen.de/cgi-bin/lika-services/ogc-free-maps.ows"
BORIS_WMS_LAYER_2026 = "hboris_feature"
BORIS_YEARS_ALL = (2020, 2022, 2024, 2026)

# --- Schlüssel der AdV-BORIS-Codelisten ---------------------------------
ENTWICKLUNGSZUSTAND = {
    "B": "Baureifes Land",
    "R": "Rohbauland",
    "E": "Bauerwartungsland",
    "LF": "Land- und forstwirtschaftliche Fläche",
    "SF": "Sonstige Fläche",
}

# Nutzungsarten (boris:nutzung/art). Achtung: die Gutachterausschüsse
# verschlüsseln uneinheitlich -- Frankfurt und Darmstadt nutzen das grobe "W",
# Wiesbaden dagegen die BauNVO-Gebietstypen "WR"/"WA". Wer nur auf "W" filtert,
# verliert ganze Städte.
NUTZUNG_WOHNEN = {"W", "WR", "WA", "WS", "WB"}
NUTZUNG_GEMISCHT = {"M", "MI", "MK", "MD", "MU"}
NUTZUNG_WOHNEN_ERWEITERT = NUTZUNG_WOHNEN | NUTZUNG_GEMISCHT

# --- Fluglärm ------------------------------------------------------------
# HLNUG Umgebungslärmkartierung (Lden/Lnight) - konkrete Endpunkte werden in
# fetch_noise.py aufgelöst und hier nach Verifikation eingetragen.
NOISE_WMS_CANDIDATES = [
    "https://www.gds-srv.hessen.de/cgi-bin/lika-services/ogc-free-maps.ows",
]

# --- Routenänderungen (Treatment-Definitionen) ---------------------------
# 1) "Cindy S": geänderte Abflugroute, rechtsverbindlich seit 10.07.2025,
#    einjähriger Probebetrieb. Mehrbelastung im Süden/Südosten.
CINDY_S_INKRAFT = "2025-07-10"
CINDY_S_TREATMENT_GEMEINDEN = [
    "Erzhausen",
    "Egelsbach",
    "Darmstadt",  # v.a. Darmstadt-Nord (Arheilgen/Wixhausen)
]
# Entlastung durch seltenere Südumfliegung
CINDY_S_ENTLASTUNG_GEMEINDEN = [
    "Wiesbaden",
    "Hochheim am Main",
]

# 2) Weiterentwickeltes Betriebskonzept: angekündigt 06.05.2026,
#    Umsetzung frühestens 2028 -> nur Ankündigungseffekt analysierbar.
BETRIEBSKONZEPT_ANKUENDIGUNG = "2026-05-06"
BETRIEBSKONZEPT_TREATMENT_GEMEINDEN = [
    "Flörsheim am Main",
    "Hattersheim am Main",  # Stadtteil Eddersheim
]

# --- Lärmklassen für Karte und Modelle ----------------------------------
# Bezugsgröße ist der Tagespegel LAeq (06-22 Uhr) der UNH-Konturen. Die
# niedrigste veröffentlichte Isophone liegt bei 48 dB(A); alles darunter
# bildet die Referenzkategorie "unter 48".
LDEN_BINS = [0, 48, 50, 55, 60, 65, 200]
LDEN_LABELS = ["unter 48", "48-50", "50-55", "55-60", "60-65", "65+"]
LDEN_REFERENZ = "unter 48"

# Ersatzwert für Zonen außerhalb der niedrigsten Kontur
PEGEL_UNTER_KONTUR = 44.0

# Nachtpegel (LAeq 22-6 Uhr). Die Konturen beginnen bei 43 dB(A) und reichen
# wegen des Nachtflugverbots in Frankfurt weniger weit ins Umland als tags.
LNIGHT_BINS = [0, 43, 45, 48, 200]
LNIGHT_LABELS = ["unter 43", "43-45", "45-48", "48 und mehr"]
LNIGHT_REFERENZ = "unter 43"
PEGEL_UNTER_KONTUR_NACHT = 39.0

# Schwelle, ab der die Literatur einen Preiseffekt erwartet
LDEN_SCHWELLE = 50.0

# --- Netz-Etikette -------------------------------------------------------
USER_AGENT = (
    "Fluglaerm-Immobilien-Analyse/0.1 (Open-Data-Auswertung; "
    "Kontakt via GitHub Luis-Rong/Reg.-Immobilienpreise-Fluglaerm)"
)
REQUEST_DELAY_S = 0.25  # Pause zwischen Punktabfragen am WMS

"""Fluglärm und Immobilienwerte rund um den Frankfurter Flughafen (Gradio).

Einstiegspunkt für den Hugging-Face-Space. Die Streamlit-Fassung unter
app/streamlit_app.py bleibt für den lokalen Gebrauch bestehen; beide lesen
dieselben aufbereiteten Dateien aus data/processed und results.
"""

from __future__ import annotations

import html as html_lib
import json
from pathlib import Path

import branca.colormap as cm
import folium
import geopandas as gpd
import gradio as gr
import numpy as np
import pandas as pd
import requests
from folium.plugins import Fullscreen
from shapely.geometry import Point

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "processed"
RESULTS = ROOT / "results"

FRA = (50.0333, 8.5706)
STICHTAGE = [2020, 2022, 2024, 2026]

NOMINATIM_AGENT = (
    "Fluglaerm-Immobilien-Analyse/0.1 "
    "(github.com/Luis-Rong/Reg.-Immobilienpreise-Fluglaerm)"
)

DARSTELLUNGEN = {
    "Fluglärm (Tagespegel)": {
        "spalte": "flug_tag_gefuellt_{jahr}",
        "einheit": "dB(A)",
        "palette": "YlOrRd",
        "erklaerung": (
            "Dauerschallpegel tagsüber (6–22 Uhr) aus den Isophonenkarten des "
            "Umwelt- und Nachbarschaftshauses. Werte unter 48 dB(A) werden nicht "
            "veröffentlicht und erscheinen hier als 44. Der Zeitregler zeigt, wie "
            "die Konturen im Verkehrseinbruch 2020/21 schrumpften."
        ),
    },
    "Bodenrichtwert": {
        "spalte": "bodenrichtwert_{jahr}",
        "einheit": "€/m²",
        "palette": "YlGnBu",
        "erklaerung": "Amtlicher Bodenrichtwert zum gewählten Stichtag (BORIS Hessen).",
    },
    "Geschätzter Lärmeffekt": {
        "spalte": "effekt_prozent",
        "einheit": "%",
        "palette": "RdYlGn",
        "erklaerung": (
            "Modellbasierter Bodenwertunterschied gegenüber sonst vergleichbaren "
            "Zonen unter 48 dB(A). Gilt je Lärmklasse und damit für alle Stichtage "
            "gleich — der Zeitregler bleibt hier ohne Wirkung."
        ),
    },
    "Wertentwicklung": {
        "spalte": "brw_veraenderung_pct",
        "einheit": "%",
        "palette": "RdYlGn",
        "erklaerung": (
            "Veränderung des Bodenrichtwerts zwischen den beiden jüngsten "
            "Stichtagen (01.01.2024 → 01.01.2026). Große Prozentwerte finden sich "
            "fast nur außerhalb des Baulands, wo die Ausgangswerte unter einem "
            "Euro liegen."
        ),
    },
}

FLAECHENARTEN = {
    "Wohnbauland (Grundlage der Analyse)": lambda d: d[
        d["nutzung_gruppe"].eq("wohnen") & d["ist_bauland"]
    ],
    "Alles Bauland (inkl. gemischt und gewerblich)": lambda d: d[d["ist_bauland"]],
    "Alle Zonen (auch Acker, Wald, Sonderflächen)": lambda d: d,
}


# --- Daten einmalig laden -------------------------------------------------
KARTE = gpd.read_parquet(DATA / "karte.parquet")
KONTUREN = gpd.read_parquet(DATA / "konturen_karte.parquet")
MODELLE = json.loads((RESULTS / "modelle.json").read_text(encoding="utf-8"))
GREIX = json.loads((RESULTS / "greix_referenz.json").read_text(encoding="utf-8"))
GREIX_REIHE = pd.read_parquet(DATA / "greix_staedte.parquet")

GEMEINDEN = sorted(KARTE["gemeinde"].dropna().unique().tolist())


# --- Karte ----------------------------------------------------------------
def _farbskala(werte: pd.Series, palette: str, beschriftung: str):
    """Stufenskala, gestutzt aufs 2.–98. Perzentil.

    Ohne Stutzung schluckt ein einzelner Ausreißer die gesamte Abstufung;
    ohne die Entdopplung der Grenzen fallen sie beim Fluglärm zusammen, weil
    über drei Viertel der Zonen denselben Ersatzwert tragen.
    """
    endlich = werte.dropna()
    if endlich.empty:
        return None

    untere, obere = np.percentile(endlich, [2, 98])
    endlich = endlich.clip(untere, obere)
    grenzen = sorted({round(float(v), 2) for v in np.quantile(endlich, np.linspace(0, 1, 8))})

    if len(grenzen) < 4:
        lo, hi = float(endlich.min()), float(endlich.max())
        hi = hi if hi > lo else lo + 1.0
        grenzen = list(np.linspace(lo, hi, 6).round(2))

    n_farben = max(3, min(9, len(grenzen) - 1))
    basis = getattr(cm.linear, f"{palette}_{n_farben:02d}", cm.linear.YlOrRd_07)
    grenzen = list(np.linspace(grenzen[0], grenzen[-1], n_farben + 1).round(2))

    return cm.StepColormap(
        colors=basis.colors[:n_farben],
        index=grenzen,
        vmin=grenzen[0],
        vmax=grenzen[-1],
        caption=beschriftung,
    )


def zeichne_karte(gdf, spalte, palette, einheit, titel, fundstelle=None) -> str:
    mitte = (fundstelle[0], fundstelle[1]) if fundstelle else FRA
    m = folium.Map(
        location=mitte, zoom_start=14 if fundstelle else 11, tiles="CartoDB positron"
    )
    Fullscreen().add_to(m)

    daten = gdf[gdf[spalte].notna()].copy()
    if daten.empty:
        return _einbetten(m)

    skala = _farbskala(daten[spalte], palette, f"{titel} in {einheit}")

    def stil(feature):
        wert = feature["properties"].get(spalte)
        return {
            "fillColor": skala(wert) if (skala and wert is not None) else "#cccccc",
            "color": "#555555",
            "weight": 0.3,
            "fillOpacity": 0.75,
        }

    felder = ["gemeinde", "gemarkung", spalte]
    aliase = ["Gemeinde:", "Gemarkung:", f"{titel} ({einheit}):"]
    for extra, alias in (
        ("nutzungsklasse", "Nutzung:"),
        ("bodenrichtwert_2024", "Bodenrichtwert 2024 (€/m²):"),
        ("bodenrichtwert_2026", "Bodenrichtwert 2026 (€/m²):"),
        ("flug_tag_2024", "Fluglärm Tag (dB(A)):"),
        ("brw_veraenderung_pct", "Wertänderung 2024→2026 (%):"),
        ("datenquelle", "Quelle:"),
    ):
        if extra in daten.columns and extra != spalte:
            felder.append(extra)
            aliase.append(alias)

    folium.GeoJson(
        daten[felder + ["geometry"]].to_json(),
        style_function=stil,
        highlight_function=lambda _: {"weight": 2.5, "color": "#000000"},
        tooltip=folium.GeoJsonTooltip(fields=felder, aliases=aliase, sticky=True),
        name="Bodenrichtwertzonen",
    ).add_to(m)
    if skala:
        skala.add_to(m)

    farben = {50: "#3182bd", 55: "#f0a30a", 60: "#e6550d", 65: "#a50f15"}
    for _, zeile in KONTUREN.iterrows():
        folium.GeoJson(
            zeile.geometry.__geo_interface__,
            style_function=lambda _f, c=farben.get(int(zeile["pegel"]), "#666"): {
                "color": c, "weight": 2, "fill": False, "dashArray": "6,4",
            },
            tooltip=f"Fluglärmkontur {int(zeile['pegel'])} dB(A)",
            name=f"Kontur {int(zeile['pegel'])} dB",
        ).add_to(m)

    folium.LayerControl(collapsed=True).add_to(m)
    folium.Marker(
        FRA, tooltip="Flughafen Frankfurt",
        icon=folium.Icon(color="gray", icon="plane", prefix="fa"),
    ).add_to(m)

    if fundstelle:
        folium.Marker(
            (fundstelle[0], fundstelle[1]),
            tooltip=fundstelle[2],
            icon=folium.Icon(color="red", icon="map-pin", prefix="fa"),
        ).add_to(m)

    return _einbetten(m)


def _einbetten(m: folium.Map) -> str:
    """Folium-Karte als iframe einbetten.

    Gradio rendert übergebenes HTML im Seitenkontext; die Leaflet-Skripte
    brauchen aber ein eigenes Dokument. srcdoc liefert genau das.
    """
    roh = m.get_root().render()
    return (
        f'<iframe srcdoc="{html_lib.escape(roh, quote=True)}" '
        'style="width:100%;height:600px;border:none;border-radius:8px;"></iframe>'
    )


# --- Adresssuche ----------------------------------------------------------
_GEO_CACHE: dict[str, tuple | None] = {}


def geokodiere(adresse: str):
    """Adresse über Nominatim auflösen; Ergebnisse werden zwischengespeichert.

    Die Nutzungsbedingungen von OpenStreetMap verlangen einen sprechenden
    User-Agent und höchstens eine Anfrage je Sekunde.
    """
    schluessel = adresse.strip().lower()
    if schluessel in _GEO_CACHE:
        return _GEO_CACHE[schluessel]

    try:
        antwort = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": adresse, "format": "json", "limit": 1, "countrycodes": "de"},
            headers={"User-Agent": NOMINATIM_AGENT},
            timeout=20,
        )
        antwort.raise_for_status()
        treffer = antwort.json()
    except (requests.RequestException, ValueError):
        _GEO_CACHE[schluessel] = None
        return None

    ergebnis = (
        (float(treffer[0]["lat"]), float(treffer[0]["lon"]),
         treffer[0].get("display_name", adresse))
        if treffer
        else None
    )
    _GEO_CACHE[schluessel] = ergebnis
    return ergebnis


def zone_an_punkt(lat: float, lon: float):
    punkt = Point(lon, lat)
    treffer = KARTE[KARTE.geometry.contains(punkt)]
    if not treffer.empty:
        return treffer.iloc[0]
    entfernung = KARTE.geometry.distance(punkt)
    if entfernung.empty or entfernung.min() > 0.01:
        return None
    return KARTE.loc[entfernung.idxmin()]


# --- Ansicht aktualisieren -------------------------------------------------
def aktualisiere(darstellung, jahr, flaechenart, gemeinden, adresse):
    konfig = DARSTELLUNGEN[darstellung]
    jahr = int(jahr)
    spalte = konfig["spalte"].format(jahr=jahr)

    gefiltert = FLAECHENARTEN[flaechenart](KARTE)
    if gemeinden:
        gefiltert = gefiltert[gefiltert["gemeinde"].isin(gemeinden)]

    fundstelle = None
    suchtext = ""
    if adresse and adresse.strip():
        ort = geokodiere(adresse.strip())
        if ort is None:
            suchtext = (
                f"**Keine Koordinate für „{adresse}“ gefunden.** Hilfreich ist "
                "meist die Form „Straße Hausnummer, Ort“."
            )
        else:
            lat, lon, bezeichnung = ort
            zone = zone_an_punkt(lat, lon)
            if zone is None:
                suchtext = (
                    f"**„{bezeichnung}“ liegt außerhalb des Untersuchungsgebiets.** "
                    "Abgedeckt ist der hessische Raum um den Flughafen."
                )
            else:
                fundstelle = (lat, lon, bezeichnung, zone)
                pegel = zone.get(f"flug_tag_{jahr}")
                brw = zone.get(f"bodenrichtwert_{jahr}")
                effekt = zone.get("effekt_prozent")
                suchtext = (
                    f"**{bezeichnung}**\n\n"
                    f"| | |\n|---|---|\n"
                    f"| Gemeinde | {zone.get('gemeinde', '—')} |\n"
                    f"| Fluglärm tags {jahr} | "
                    f"{f'{pegel:.0f} dB(A)' if pd.notna(pegel) else 'unter 48 dB(A)'} |\n"
                    f"| Bodenrichtwert {jahr} | "
                    f"{f'{brw:,.0f} €/m²'.replace(',', '.') if pd.notna(brw) else '—'} |\n"
                    f"| Geschätzter Lärmeffekt | "
                    f"{f'{effekt:+.1f} %' if pd.notna(effekt) else '—'} |\n"
                )

    if spalte not in gefiltert.columns:
        return "<p>Für diese Darstellung fehlen Daten.</p>", suchtext, ""

    mit_wert = int(gefiltert[spalte].notna().sum())
    laerm_spalte = f"flug_tag_{jahr}"
    belastet = (
        int(gefiltert[laerm_spalte].notna().sum()) if laerm_spalte in gefiltert else 0
    )
    brw_spalte = f"bodenrichtwert_{jahr}"
    median = (
        gefiltert[brw_spalte].median() if brw_spalte in gefiltert else float("nan")
    )

    kennzahlen = (
        f"**{len(gefiltert):,}** Zonen in Auswahl &nbsp;·&nbsp; "
        f"**{mit_wert:,}** davon mit Wert &nbsp;·&nbsp; "
        f"Median Bodenrichtwert {jahr}: **"
        f"{median:,.0f} €/m²**" if pd.notna(median) else "—"
    ).replace(",", ".")
    kennzahlen += f" &nbsp;·&nbsp; **{belastet:,}** Zonen in Lärmkonturen ({jahr})".replace(",", ".")

    karten_html = zeichne_karte(
        gefiltert, spalte, konfig["palette"], konfig["einheit"], darstellung, fundstelle
    )
    return karten_html, suchtext, kennzahlen


# --- Tabellen --------------------------------------------------------------
def koeffiziententabelle(modell: dict) -> pd.DataFrame:
    zeilen = []
    for k in modell["koeffizienten"]:
        ist_boden = "effekt_bodenwert_prozent" in k
        wert = k.get("effekt_bodenwert_prozent", k.get("effekt_miete_prozent"))
        zeile = {
            "Merkmal": k["term"],
            f"Effekt auf {'Bodenwert' if ist_boden else 'Miete'}": f"{wert:+.1f} %",
            "95 %-Konfidenzintervall": f"{k['ki_unten']:+.1f} bis {k['ki_oben']:+.1f} %",
            "p-Wert": f"{k['p_wert']:.4f}",
            "signifikant (5 %)": "ja" if k["signifikant_5pct"] else "nein",
        }
        if ist_boden:
            immo = k["effekt_immobilie_prozent"]
            zeile["≈ auf Immobilienwert"] = f"{immo[0]:+.1f} bis {immo[1]:+.1f} %"
        zeilen.append(zeile)
    return pd.DataFrame(zeilen)


def spezifikationstabelle() -> pd.DataFrame:
    df = pd.DataFrame(MODELLE["spezifikationsvergleich"])
    return df.rename(
        columns={
            "spezifikation": "Kontrollvariablen",
            "n": "n",
            "r2": "R²",
            "effekt_je_db_prozent": "Effekt je dB (%)",
            "p_wert": "p-Wert",
        }
    )


def greix_verlauf() -> pd.DataFrame:
    ffm = GREIX_REIHE[GREIX_REIHE["stadt"].str.contains("Frankfurt", na=False)]
    verlauf = ffm.groupby(["jahr", "objekttyp"])["preis_eur_qm"].mean().reset_index()
    # Jahr als Text, sonst beschriftet Gradio die Achse mit Tausendertrennung
    # und Nachkommastelle ("2.010,0").
    verlauf["jahr"] = verlauf["jahr"].astype(int).astype(str)
    return verlauf.rename(
        columns={"jahr": "Jahr", "objekttyp": "Objekttyp", "preis_eur_qm": "€/m²"}
    ).round({"€/m²": 0})


# --- Texte -----------------------------------------------------------------
KARTEN_HILFE = """
**Die Flächen** sind amtliche Bodenrichtwertzonen — Gebiete, für die der
Gutachterausschuss einen einheitlichen Bodenwert festlegt. Sie folgen der
Bebauungsstruktur, sind also kein gleichmäßiges Raster.

| Ansicht | Farbe bedeutet | Datentyp |
|---|---|---|
| Fluglärm | Dauerschallpegel tagsüber, hell = leise | Rohdaten |
| Bodenrichtwert | Preis je m², hell = günstig | Rohdaten |
| Geschätzter Lärmeffekt | Wertabschlag laut Modell, rot = Abschlag | **Modellergebnis** |
| Wertentwicklung | Preisänderung 2024 → 2026, rot = gefallen | Rohdaten |

Nur „Geschätzter Lärmeffekt” zeigt ein Regressionsergebnis. Bei den anderen
bedeutet Dunkelrot nicht „durch Lärm verursacht”, sondern schlicht „hier ist es
laut” bzw. „hier ist es teuer” — Frankfurt-Sachsenhausen ist beides, weil
zentral. Die gestrichelten Linien sind die Lärmkonturen bei 50/55/60/65 dB(A);
sie helfen beim Gegenprüfen.

**Mainz sieht anders aus als der Rest der Karte** — kleinere, gleichmäßig
gerasterte Quadrate statt der unregelmäßigen Zonenzuschnitte. Das liegt an der
Quelle: Für Rheinland-Pfalz gibt es keinen offenen Massendownload der
Zonenpolygone, nur einen abfragbaren Kartendienst (WMS). Jedes Quadrat ist ein
450-Meter-Rasterpunkt mit dem dort geltenden Bodenrichtwert — technisch näher
am ursprünglich vorgeschwebten „Kachelsystem” als die amtlichen Zonen. Die
Mainzer Kacheln fließen **nicht** in die Regressionsmodelle ein (Tab
„Regressionsergebnisse”); dort bleibt es bei Hessen. Sie dienen der Karte und
dem visuellen Abgleich mit der entlasteten Seite von „Cindy S”.
"""

GRENZEN = """
### Woher die Daten kommen

| Größe | Quelle | Stand |
|---|---|---|
| Bodenrichtwerte | BORIS Hessen (HVBG), WFS und WMS-Auskunft | Stichtage 01.01.2020 / 2022 / 2024 / 2026 |
| Fluglärmkonturen | Umwelt- und Nachbarschaftshaus, LAeq Tag/Nacht | Jahreswerte 2013–2024 |
| Straßen-, Schienen-, Industrielärm | HLNUG, EU-Umgebungslärmkartierung | 2022 |
| Sozialstruktur | Zensus 2022, Statistisches Bundesamt (1-km-Gitter) | 15.05.2022 |
| Kaufpreise | GREIX, Kiel Institut | Quartalswerte 2010–2026 |
| Mainzer Bodenrichtwerte | VBORIS RLP Basisdienst (WMS-Punktraster) | Stichtage 2024 / 2026 |
| Lagefaktoren | OpenStreetMap via Overpass | laufend |

Alle Quellen sind kostenfrei und ohne Anmeldung nutzbar.

### Was dieses Tool nicht kann

- **Bodenwerte sind keine Kaufpreise.** Gemessen wird der Wert des Grundstücks
  für ein normiertes Referenzgrundstück je Zone. Die Umrechnung auf den
  Immobilienwert unterstellt eine Bodenwertquote von 30–50 %.
- **Unterhalb von 48 dB(A) ist der Lärm unbekannt.** Alle leiseren Zonen bilden
  gemeinsam die Referenzgruppe; einen Gradienten gibt es dort nicht.
- **Korrelation ist nicht Kausalität.** Der Spezifikationsvergleich zeigt, wie
  stark die Schätzung von den Kontrollvariablen abhängt.
- **Für 2025 fehlen Lärmkonturen.** Die Wirkung von „Cindy S“ lässt sich
  deshalb nicht über gemessene Pegel abbilden, sondern nur über die betroffenen
  Gemeinden.
- **Mainz ist auf der Karte, aber nicht im Modell.** Die geschützte OGC-API
  von BORIS RLP verlangt eine Freischaltung durch den Datenanbieter. Über den
  frei zugänglichen VBORIS-Basisdienst (WMS statt WFS) liefert ein
  450-Meter-Punktraster trotzdem 345 Kacheln für 2024 und 2026 — sichtbar auf
  der Karte, aber wegen der abweichenden Datenstruktur nicht Teil der
  Regressionsmodelle.

### Lizenz

Bodenrichtwerte © HVBG · Umgebungslärm © HLNUG · Fluglärmkonturen ©
Gemeinnützige Umwelthaus GmbH · Zensus © Statistisches Bundesamt ·
Kaufpreise © Kiel Institut (GREIX) · Karten © OpenStreetMap-Mitwirkende (ODbL)
"""


def _kernaussage() -> str:
    kern = MODELLE["A2"]["koeffizienten"][0]
    immo = kern["effekt_immobilie_prozent"]
    return (
        "### Jedes zusätzliche dB(A) kostet rund "
        f"{abs(kern['effekt_bodenwert_prozent']):.1f} % Bodenwert\n\n"
        f"(p = {kern['p_wert']}, entspricht etwa {abs(immo[0]):.1f}–{abs(immo[1]):.1f} % "
        "auf den Gesamtwert einer Immobilie)\n\n"
        "**Warum zwei Zahlen?** Gemessen wird der reine Bodenwert. Da der Boden im "
        "Rhein-Main-Gebiet grob 30–50 % des Immobilienwerts ausmacht und das Gebäude "
        "selbst nicht leiser oder lauter wird, fällt der Effekt auf den Gesamtwert "
        "kleiner aus. Die Literaturwerte von 0,5–1,3 % je dB beziehen sich auf den "
        "Gesamtwert — dort liegt dieses Ergebnis also genau."
    )


# --- Oberfläche ------------------------------------------------------------
with gr.Blocks(title="Fluglärm & Immobilienwerte Frankfurt") as demo:
    gr.Markdown(
        "# ✈️ Fluglärm und Immobilienwerte rund um den Frankfurter Flughafen\n"
        "Hedonische Regression auf amtlichen Bodenrichtwerten (BORIS Hessen), "
        "Fluglärm-Isophonen des Umwelt- und Nachbarschaftshauses und der "
        "Sozialstruktur des Zensus 2022 — gegengeprüft an notariell beurkundeten "
        "Kaufpreisen (GREIX)."
    )

    with gr.Tabs():
        with gr.Tab("Karte"):
            with gr.Row():
                with gr.Column(scale=1):
                    darstellung = gr.Radio(
                        list(DARSTELLUNGEN),
                        value="Fluglärm (Tagespegel)",
                        label="Was soll eingefärbt werden?",
                    )
                    jahr = gr.Slider(
                        minimum=2020, maximum=2026, step=2, value=2024,
                        label="Stichtag",
                        info="Bodenrichtwerte zum 01.01.; Lärm aus dem Jahr davor",
                    )
                    flaechenart = gr.Dropdown(
                        list(FLAECHENARTEN),
                        value=list(FLAECHENARTEN)[0],
                        label="Welche Flächen?",
                        info="Der Entwicklungszustand treibt die Bodenwerte stärker als alles andere",
                    )
                    gemeinden = gr.Dropdown(
                        GEMEINDEN, value=[], multiselect=True,
                        label="Auf Gemeinden eingrenzen",
                    )
                    adresse = gr.Textbox(
                        label="Adresse nachschlagen",
                        placeholder="z. B. Ringstraße 1, Raunheim",
                        info="Geokodierung über Nominatim (OpenStreetMap)",
                    )
                    suchergebnis = gr.Markdown()
                with gr.Column(scale=3):
                    kennzahlen = gr.Markdown()
                    karte_html = gr.HTML()
                    erklaerung = gr.Markdown(
                        DARSTELLUNGEN["Fluglärm (Tagespegel)"]["erklaerung"]
                    )

            with gr.Accordion("Wie lese ich diese Karte?", open=False):
                gr.Markdown(KARTEN_HILFE)

        with gr.Tab("Regressionsergebnisse"):
            gr.Markdown(_kernaussage())

            gr.Markdown(
                "#### Modell A: Wertunterschied je Lärmklasse\n"
                f"{MODELLE['A']['beschreibung']}  \n"
                f"n = {MODELLE['A']['n']}, R² = {MODELLE['A']['r2']}"
            )
            gr.Dataframe(koeffiziententabelle(MODELLE["A"]), interactive=False, wrap=True)

            gr.Markdown(
                "#### Wie stabil ist das Ergebnis?\n"
                "Je mehr Lagefaktoren kontrolliert werden, desto kleiner der "
                "geschätzte Effekt. Das zeigt, wie stark Fluglärm mit Lagequalität "
                "und Stadtgeschichte verwoben ist — die untersten Zeilen sind die "
                "belastbaren."
            )
            gr.Dataframe(spezifikationstabelle(), interactive=False, wrap=True)

            if "N" in MODELLE:
                _n2 = MODELLE["N2"]["koeffizienten"][0]
                _a2 = MODELLE["A2"]["koeffizienten"][0]
                _korr = MODELLE.get("TN", {}).get("korrelation_tag_nacht")
                gr.Markdown(
                    f"#### Nachtlärm\n{MODELLE['N']['beschreibung']}  \n"
                    f"Stetig: {_n2['effekt_bodenwert_prozent']:+.2f} % je dB(A), "
                    f"p = {_n2['p_wert']}"
                )
                gr.Dataframe(koeffiziententabelle(MODELLE["N"]), interactive=False, wrap=True)
                gr.Markdown(
                    "> Je dB wirkt der Nachtpegel etwas stärker als der Tagespegel "
                    f"({_n2['effekt_bodenwert_prozent']:+.2f} % gegenüber "
                    f"{_a2['effekt_bodenwert_prozent']:+.2f} %) — passend zur "
                    "Lärmwirkungsforschung, die Nachtlärm als den schädlicheren Teil "
                    f"einstuft. Sauber trennen lassen sie sich nicht: Korrelation {_korr}."
                )

            if "M" in MODELLE:
                _m = MODELLE["M"]
                gr.Markdown(
                    "#### Gegenprobe mit einer anderen Zielgröße: der Miete\n"
                    f"{_m['beschreibung']}  \nn = {_m['n']}, R² = {_m['r2']}"
                )
                gr.Dataframe(koeffiziententabelle(_m), interactive=False, wrap=True)
                gr.Markdown(
                    "> Hier zeigt sich **kein** Effekt. Das ist kein Gegenbeweis, "
                    "sondern eine Frage der Auflösung: Die Zensus-Miete liegt nur im "
                    "1-km-Raster vor, während der Fluglärm zonenscharf variiert. "
                    "Innerhalb einer Rasterzelle ist die Miete konstant, der Lärm "
                    "nicht — das zieht den Koeffizienten gegen null."
                )

            _b = MODELLE["B"]
            gr.Markdown(
                f"#### Modell B: Panel mit Zonen-Fixen-Effekten\n{_b['beschreibung']}  \n"
                f"{_b['zonen']} Zonen, davon {_b['zonen_mit_laermvariation']} mit Pegeländerung"
            )
            gr.Dataframe(koeffiziententabelle(_b), interactive=False, wrap=True)
            gr.Markdown(
                "> Dieses Modell nutzt nur Zonen, deren Pegel sich über die Zeit "
                "ändert — im Kern den Verkehrseinbruch 2020/21. Dass hier nichts "
                "herauskommt, passt zur Theorie: Eine erkennbar vorübergehende "
                "Lärmpause kapitalisiert sich nicht in dauerhaften Bodenwerten."
            )

        with gr.Tab("Routenänderungen"):
            gr.Markdown("### Hat sich der Zusammenhang nach den Routenänderungen verändert?")
            gr.Markdown("#### 1. Geänderte Abflugroute „Cindy S“ (seit 10.07.2025)")
            if "C" in MODELLE:
                _c = MODELLE["C"]
                gr.Markdown(
                    f"{_c['beschreibung']}  \n{_c['treatment_zonen']} Treatment-Zonen "
                    f"gegen {_c['kontroll_zonen']} Kontrollzonen"
                )
                gr.Dataframe(koeffiziententabelle(_c), interactive=False, wrap=True)
            gr.Markdown(
                "Die Route gilt seit dem 10. Juli 2025 im einjährigen Probebetrieb. "
                "Zusätzlich belastet werden Erzhausen, Egelsbach und Darmstadt-Nord; "
                "entlastet wird die Südumfliegung über Mainz und Wiesbaden. Zwischen "
                "Inkrafttreten und dem Stichtag 01.01.2026 liegen nur sechs Monate. "
                "Der Vergleich mit echten Kaufpreisen im nächsten Tab zeigt, dass "
                "Bodenrichtwerte dem Markt rund einen Zyklus hinterherhinken — ein "
                "Nullergebnis ist hier also erwartbar und kein Beleg für "
                "Wirkungslosigkeit."
            )

            gr.Markdown("#### 2. Weiterentwickeltes Betriebskonzept (angekündigt 06.05.2026)")
            gr.Markdown(
                "Mehr Abflüge Richtung Nordwesten, betroffen wären vor allem "
                "Flörsheim und Hattersheim-Eddersheim; umgesetzt frühestens 2028. "
                "Der aktuellste Stichtag ist der 01.01.2026 und liegt damit **vor** "
                "der Ankündigung — ein Ankündigungseffekt kann in diesen Daten gar "
                "nicht enthalten sein."
            )
            if "D" in MODELLE:
                gr.Markdown("Ausgangsmessung für spätere Stichtage:")
                gr.Dataframe(koeffiziententabelle(MODELLE["D"]), interactive=False, wrap=True)

        with gr.Tab("Referenz: echte Kaufpreise"):
            gr.Markdown(
                "### Halten die Bodenwerte, was echte Kaufpreise sagen?\n"
                "Der **GREIX** des Kiel Instituts beruht auf notariell beurkundeten "
                "Kaufpreisen — quartalsweise und ungeglättet."
            )
            gr.Dataframe(
                pd.DataFrame(GREIX["frankfurt"]["perioden"]).rename(
                    columns={
                        "zeitraum": "Stichtage",
                        "marktjahre": "Marktjahre",
                        "bodenrichtwert_wachstum_pct": "Bodenrichtwert (%)",
                        "kaufpreis_wachstum_pct": "Kaufpreis (%)",
                        "differenz_pp": "Differenz (pp)",
                    }
                ),
                interactive=False, wrap=True,
            )
            gr.Markdown(
                "> **Der wichtigste Befund dieses Vergleichs:** Die Bodenrichtwerte "
                "hinken dem Markt um rund einen Zyklus hinterher. Den Preiseinbruch "
                "von 2023 — real gut 17 % — haben sie zum Stichtag 2024 nicht "
                "abgebildet; sie gaben erst 2026 nach, als die Kaufpreise längst "
                "wieder stiegen. Für „Cindy S“ heißt das: Eine Routenänderung vom "
                "Juli 2025 kann im Stichtag 01.01.2026 praktisch nicht enthalten "
                "sein. Das ist keine Vermutung mehr, sondern hier ablesbar."
            )

            gr.Markdown("#### Kaufpreisentwicklung Frankfurt")
            gr.LinePlot(greix_verlauf(), x="Jahr", y="€/m²", color="Objekttyp", height=320)
            gr.Markdown(
                "Mittlerer Kaufpreis je m² Wohnfläche. Gipfel 2022, Einbruch 2023, "
                "Erholung ab 2024 — in den Bodenrichtwerten ist davon nichts zu sehen."
            )

            gr.Markdown("#### Frankfurter Stadtviertel nach Lage zur Einflugschneise")
            gr.Dataframe(
                pd.DataFrame(GREIX["viertel_gegen_laerm"]["gruppen"]).rename(
                    columns={
                        "lage": "Lage",
                        "viertel_anzahl": "Viertel",
                        "preis_mittel": "Ø Kaufpreis (€/m²)",
                        "kauffaelle": "Kauffälle",
                        "abstand_zu_abseits_pct": "Abstand zu abseits (%)",
                    }
                ),
                interactive=False, wrap=True,
            )
            gr.Markdown(
                "> **Vorsicht bei der Deutung:** Ein Rohvergleich ohne "
                "Kontrollvariablen. Die Viertel in der Einflugschneise — Frankfurter "
                "Westen und Süden — sind zugleich die industriell geprägten und "
                "zentrumsferneren Lagen. Die 21 % sind eine Obergrenze, nicht der "
                "Lärmeffekt. Was der Vergleich leistet: Er bestätigt die Richtung "
                "unabhängig von den Bodenrichtwerten, an echten Kaufverträgen."
            )

        with gr.Tab("Daten & Grenzen"):
            gr.Markdown(GRENZEN)

    _eingaben = [darstellung, jahr, flaechenart, gemeinden, adresse]
    _ausgaben = [karte_html, suchergebnis, kennzahlen]
    for _regler in (darstellung, jahr, flaechenart, gemeinden):
        _regler.change(aktualisiere, inputs=_eingaben, outputs=_ausgaben)
    adresse.submit(aktualisiere, inputs=_eingaben, outputs=_ausgaben)
    darstellung.change(
        lambda d: DARSTELLUNGEN[d]["erklaerung"], inputs=darstellung, outputs=erklaerung
    )
    demo.load(aktualisiere, inputs=_eingaben, outputs=_ausgaben)


if __name__ == "__main__":
    # theme gehört seit Gradio 6 an launch(), nicht mehr an den Blocks-Aufbau
    demo.launch(theme=gr.themes.Soft())

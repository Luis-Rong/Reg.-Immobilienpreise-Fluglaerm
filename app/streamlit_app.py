"""Interaktives Tool: Fluglärm und Bodenwerte rund um den Frankfurter Flughafen."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import branca.colormap as cm
import folium
import geopandas as gpd
import numpy as np
import pandas as pd
import requests
import streamlit as st
from folium.plugins import Fullscreen
from shapely.geometry import Point
from streamlit.components.v1 import html as st_html

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

DATA = ROOT / "data" / "processed"
RESULTS = ROOT / "results"

st.set_page_config(
    page_title="Fluglärm & Bodenwerte Frankfurt",
    page_icon="✈️",
    layout="wide",
)

FRA = (50.0333, 8.5706)

NOMINATIM_AGENT = (
    "Fluglaerm-Immobilien-Analyse/0.1 "
    "(github.com/Luis-Rong/Reg.-Immobilienpreise-Fluglaerm)"
)

STICHTAGE = (2020, 2022, 2024, 2026)

# "spalte" mit {jahr} folgt dem Zeitregler, feste Spalten ignorieren ihn.
DARSTELLUNGEN = {
    "Fluglärm (Tagespegel)": {
        "spalte": "flug_tag_gefuellt_{jahr}",
        "einheit": "dB(A)",
        "palette": "YlOrRd",
        "erklaerung": (
            "Dauerschallpegel tagsüber (6-22 Uhr) aus den Isophonenkarten des "
            "Umwelt- und Nachbarschaftshauses. Werte unter 48 dB(A) werden nicht "
            "veröffentlicht und sind hier als 44 dargestellt. Der Zeitregler "
            "zeigt, wie die Konturen im Verkehrseinbruch 2020/21 schrumpften "
            "und danach wieder wuchsen."
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
            "Zonen unter 48 dB(A). Aus Modell A geschätzt, gilt je Lärmklasse "
            "und damit für alle Stichtage gleich."
        ),
    },
    "Wertentwicklung": {
        "spalte": "brw_veraenderung_pct",
        "einheit": "%",
        "palette": "RdYlGn",
        "erklaerung": (
            "Veränderung des Bodenrichtwerts zwischen den beiden jüngsten "
            "Stichtagen (01.01.2024 → 01.01.2026). Dieser Zeitraum umfasst die "
            "ersten sechs Monate der geänderten Abflugroute „Cindy S\"."
        ),
    },
}


# Auswahl der Flächen. Der Entwicklungszustand ist der stärkste Treiber der
# Bodenrichtwerte überhaupt -- Bauland und Ackerland liegen zwei Größen-
# ordnungen auseinander. Die Analyse selbst läuft ausschließlich auf
# Wohnbauland; die übrigen Optionen dienen der Einordnung.
FLAECHENARTEN = {
    "Wohnbauland (Grundlage der Analyse)": lambda d: d[
        d["nutzung_gruppe"].eq("wohnen") & d["ist_bauland"]
    ],
    "Alles Bauland (inkl. gemischt und gewerblich)": lambda d: d[d["ist_bauland"]],
    "Alle Zonen (auch Acker, Wald, Sonderflächen)": lambda d: d,
}


def _stand(pfad: Path) -> float:
    """Änderungszeitpunkt als Cache-Schlüssel.

    Ohne ihn liefert der Cache nach einem erneuten Modelllauf weiterhin die
    alten Ergebnisse, bis der Server neu startet. Der Parameter darf in den
    Ladefunktionen keinen Unterstrich-Präfix tragen -- solche Argumente nimmt
    Streamlit vom Hashen aus, womit der Schlüssel wirkungslos wäre.
    """
    return pfad.stat().st_mtime


@st.cache_data
def lade_karte(stand: float) -> gpd.GeoDataFrame:
    return gpd.read_parquet(DATA / "karte.parquet")


@st.cache_data
def lade_konturen(stand: float) -> gpd.GeoDataFrame:
    return gpd.read_parquet(DATA / "konturen_karte.parquet")


@st.cache_data
def lade_modelle(stand: float) -> dict:
    return json.loads((RESULTS / "modelle.json").read_text(encoding="utf-8"))


@st.cache_data
def lade_greix(stand: float) -> dict:
    return json.loads((RESULTS / "greix_referenz.json").read_text(encoding="utf-8"))


@st.cache_data
def lade_greix_reihe(stand: float) -> pd.DataFrame:
    return pd.read_parquet(ROOT / "data" / "raw" / "greix_staedte.parquet")


def _farbskala(werte: pd.Series, palette: str, einheit: str):
    """Stufenskala aus den Daten ableiten.

    Zwei Eigenheiten der Daten machen das nötig. Erstens tragen beim Fluglärm
    über drei Viertel der Zonen denselben Ersatzwert, wodurch Quantilgrenzen
    zusammenfallen. Zweitens gibt es bei den Wertänderungen einzelne
    Ausreißer -- landwirtschaftliche Flächen springen prozentual stark, weil
    ihr Ausgangswert bei unter einem Euro liegt. Die Skala wird deshalb auf
    das 2.-98. Perzentil gestutzt, sonst läge die ganze Karte in einer Farbe.
    """
    endlich = werte.dropna()
    untere, obere = np.percentile(endlich, [2, 98])
    endlich = endlich.clip(untere, obere)
    grenzen = sorted({round(float(v), 2) for v in np.quantile(endlich, np.linspace(0, 1, 8))})

    if len(grenzen) < 4:
        lo, hi = float(endlich.min()), float(endlich.max())
        if hi <= lo:
            hi = lo + 1.0
        grenzen = list(np.linspace(lo, hi, 6).round(2))

    # branca benennt die Paletten mit der Farbanzahl als Suffix (YlOrRd_07).
    n_farben = max(3, min(9, len(grenzen) - 1))
    basis = getattr(cm.linear, f"{palette}_{n_farben:02d}", cm.linear.YlOrRd_07)
    grenzen = list(np.linspace(grenzen[0], grenzen[-1], n_farben + 1).round(2))

    return cm.StepColormap(
        colors=basis.colors[:n_farben],
        index=grenzen,
        vmin=grenzen[0],
        vmax=grenzen[-1],
        caption=einheit,
    )


def zeichne_karte(
    gdf: gpd.GeoDataFrame,
    spalte: str,
    palette: str,
    einheit: str,
    titel: str,
    fundstelle: tuple | None = None,
) -> folium.Map:
    mitte = (fundstelle[0], fundstelle[1]) if fundstelle else FRA
    m = folium.Map(
        location=mitte, zoom_start=14 if fundstelle else 11, tiles="CartoDB positron"
    )
    Fullscreen().add_to(m)

    daten = gdf[gdf[spalte].notna()].copy()
    if daten.empty:
        return m

    skala = _farbskala(daten[spalte], palette, f"{titel} in {einheit}")

    def stil(feature):
        wert = feature["properties"].get(spalte)
        return {
            "fillColor": skala(wert) if wert is not None else "#cccccc",
            "color": "#555555",
            "weight": 0.3,
            "fillOpacity": 0.75,
        }

    tooltip_felder = ["gemeinde", "gemarkung", spalte]
    aliase = ["Gemeinde:", "Gemarkung:", f"{titel} ({einheit}):"]
    for extra, alias in (
        ("nutzungsklasse", "Nutzung:"),
        ("bodenrichtwert_2024", "Bodenrichtwert 01.01.2024 (€/m²):"),
        ("bodenrichtwert_2026", "Bodenrichtwert 01.01.2026 (€/m²):"),
        ("flug_tag_2024", "Fluglärm Tag (dB(A)):"),
        ("brw_veraenderung_pct", "Wertänderung 2024→2026 (%):"),
    ):
        if extra in daten.columns and extra != spalte:
            tooltip_felder.append(extra)
            aliase.append(alias)

    folium.GeoJson(
        daten[tooltip_felder + ["geometry"]].to_json(),
        style_function=stil,
        highlight_function=lambda _: {"weight": 2.5, "color": "#000000"},
        tooltip=folium.GeoJsonTooltip(fields=tooltip_felder, aliases=aliase, sticky=True),
        name="Bodenrichtwertzonen",
    ).add_to(m)
    skala.add_to(m)

    konturen = lade_konturen(_stand(DATA / "konturen_karte.parquet"))
    farben = {50: "#3182bd", 55: "#f0a30a", 60: "#e6550d", 65: "#a50f15"}
    for _, zeile in konturen.iterrows():
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
        FRA, tooltip="Flughafen Frankfurt", icon=folium.Icon(color="gray", icon="plane", prefix="fa")
    ).add_to(m)

    if fundstelle:
        lat, lon, bezeichnung, _zone = fundstelle
        folium.Marker(
            (lat, lon),
            tooltip=bezeichnung,
            icon=folium.Icon(color="red", icon="map-pin", prefix="fa"),
        ).add_to(m)
    return m


@st.cache_data(ttl=3600, show_spinner=False)
def geokodiere(adresse: str) -> tuple[float, float, str] | None:
    """Adresse über Nominatim in Koordinaten übersetzen.

    Die Nutzungsbedingungen von OpenStreetMap verlangen einen sprechenden
    User-Agent und höchstens eine Anfrage je Sekunde; der Cache sorgt dafür,
    dass wiederholte Eingaben den Dienst nicht erneut belasten.
    """
    try:
        antwort = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": adresse,
                "format": "json",
                "limit": 1,
                "countrycodes": "de",
                "viewbox": "8.10,50.30,8.95,49.75",
                "bounded": 0,
            },
            headers={"User-Agent": NOMINATIM_AGENT},
            timeout=20,
        )
        antwort.raise_for_status()
        treffer = antwort.json()
    except (requests.RequestException, ValueError):
        return None

    if not treffer:
        return None
    t = treffer[0]
    return float(t["lat"]), float(t["lon"]), t.get("display_name", adresse)


def zone_an_punkt(gdf: gpd.GeoDataFrame, lat: float, lon: float):
    """Diejenige Zone finden, die den Punkt enthält."""
    punkt = Point(lon, lat)
    treffer = gdf[gdf.geometry.contains(punkt)]
    if treffer.empty:
        # Randlage oder Lücke zwischen Zonen: nächstgelegene Zone nehmen
        entfernung = gdf.geometry.distance(punkt)
        if entfernung.empty or entfernung.min() > 0.01:  # ~1 km in Grad
            return None
        return gdf.loc[entfernung.idxmin()]
    return treffer.iloc[0]


def koeffiziententabelle(modell: dict) -> pd.DataFrame:
    zeilen = []
    for k in modell["koeffizienten"]:
        # Modell M misst die Miete und kennt daher keine Bodenwert-Umrechnung
        ist_boden = "effekt_bodenwert_prozent" in k
        wert = k.get("effekt_bodenwert_prozent", k.get("effekt_miete_prozent"))
        zeile = {
            "Merkmal": k["term"],
            f"Effekt auf {'Bodenwert' if ist_boden else 'Miete'}": f"{wert:+.1f} %",
            "95%-Konfidenzintervall": f"{k['ki_unten']:+.1f} bis {k['ki_oben']:+.1f} %",
            "p-Wert": f"{k['p_wert']:.4f}",
            "signifikant (5 %)": "ja" if k["signifikant_5pct"] else "nein",
        }
        if ist_boden:
            immo = k["effekt_immobilie_prozent"]
            zeile["≈ Effekt auf Immobilienwert"] = f"{immo[0]:+.1f} bis {immo[1]:+.1f} %"
        zeilen.append(zeile)
    return pd.DataFrame(zeilen)


# --------------------------------------------------------------------------
karte = lade_karte(_stand(DATA / "karte.parquet"))
modelle = lade_modelle(_stand(RESULTS / "modelle.json"))

st.title("✈️ Fluglärm und Immobilienwerte rund um den Frankfurter Flughafen")
st.caption(
    "Hedonische Regression auf amtlichen Bodenrichtwerten (BORIS Hessen) und "
    "Fluglärmkonturen des Umwelt- und Nachbarschaftshauses"
)

with st.sidebar:
    st.header("Karte")
    auswahl = st.radio("Was soll eingefärbt werden?", list(DARSTELLUNGEN), index=0)
    konfig = DARSTELLUNGEN[auswahl]
    zeitabhaengig = "{jahr}" in konfig["spalte"]

    jahr = st.select_slider(
        "Stichtag",
        options=STICHTAGE,
        value=2024,
        disabled=not zeitabhaengig,
        help=(
            "Bodenrichtwerte gelten jeweils zum 01.01.; der Lärm stammt aus dem "
            "Kalenderjahr davor. Für diese Darstellung ohne Wirkung."
            if not zeitabhaengig
            else "Bodenrichtwerte zum 01.01., Lärm aus dem Kalenderjahr davor."
        ),
    )
    spalte = konfig["spalte"].format(jahr=jahr)

    flaechenart = st.selectbox(
        "Welche Flächen?",
        list(FLAECHENARTEN),
        index=0,
        help=(
            "Bodenrichtwerte hängen vor allem am Entwicklungszustand: "
            "Bauland kostet dreistellig je m², Ackerland unter 10 €. Ein "
            "gemeinsamer Blick auf beides sagt wenig über Fluglärm aus."
        ),
    )
    gemeinden = sorted(karte["gemeinde"].dropna().unique())
    filter_gemeinde = st.multiselect("Auf Gemeinden eingrenzen", gemeinden)

    st.divider()
    adresse = st.text_input(
        "Adresse nachschlagen",
        placeholder="z. B. Frankfurter Straße 1, Raunheim",
        help=(
            "Sucht die Bodenrichtwertzone zu einer Adresse und zeigt Lärmpegel, "
            "Bodenwert und geschätzten Lärmeffekt. Geokodierung über Nominatim "
            "(OpenStreetMap)."
        ),
    )

    st.divider()
    st.caption(konfig["erklaerung"])

gefiltert = FLAECHENARTEN[flaechenart](karte)
if filter_gemeinde:
    gefiltert = gefiltert[gefiltert["gemeinde"].isin(filter_gemeinde)]

tab_karte, tab_modelle, tab_wandel, tab_referenz, tab_daten = st.tabs(
    [
        "Karte",
        "Regressionsergebnisse",
        "Routenänderungen",
        "Referenz: echte Kaufpreise",
        "Daten & Grenzen",
    ]
)

with tab_karte:
    with st.expander("Wie lese ich diese Karte?"):
        st.markdown(
            """
**Die Flächen** sind amtliche Bodenrichtwertzonen — Gebiete, für die der
Gutachterausschuss einen einheitlichen Bodenwert festlegt. Sie folgen der
Bebauungsstruktur, sind also kein gleichmäßiges Raster: In der Innenstadt
liegen viele kleine Zonen nebeneinander, am Rand einzelne große.

**Die vier Ansichten** zeigen jeweils eine andere Größe:

| Ansicht | Farbe bedeutet | Skala |
|---|---|---|
| Fluglärm | Dauerschallpegel tagsüber | hell = leise, dunkelrot = laut |
| Bodenrichtwert | Preis je m² Grundstück | hell = günstig, dunkelblau = teuer |
| Geschätzter Lärmeffekt | Modellergebnis je Lärmklasse | rot = Wertabschlag, grün = kein Abschlag |
| Wertentwicklung | Preisänderung 2024 → 2026 | rot = gefallen, grün = gestiegen |

**Wichtig:** Nur die Ansicht „Geschätzter Lärmeffekt" zeigt ein
Regressionsergebnis. Die anderen drei zeigen Rohdaten — dort ist Dunkelrot
nicht „durch Lärm verursacht", sondern einfach „hier ist es laut" bzw. „hier
ist es teuer".

**Die gestrichelten Linien** sind die Fluglärmkonturen bei 50, 55, 60 und
65 dB(A). Sie helfen beim Abgleich: Liegt eine dunkle Zone innerhalb der
Konturen oder nur zufällig daneben?
"""
        )

    fundstelle = None
    if adresse.strip():
        ort = geokodiere(adresse.strip())
        if ort is None:
            st.warning(
                f"Für „{adresse}\" wurde keine Koordinate gefunden. Hilfreich ist "
                "meist die Form „Straße Hausnummer, Ort\"."
            )
        else:
            lat, lon, bezeichnung = ort
            zone = zone_an_punkt(karte, lat, lon)
            if zone is None:
                st.warning(
                    f"„{bezeichnung}\" liegt außerhalb des Untersuchungsgebiets — "
                    "abgedeckt ist der hessische Raum um den Flughafen."
                )
            else:
                fundstelle = (lat, lon, bezeichnung, zone)
                st.success(f"Gefunden: {bezeichnung}")
                a1, a2, a3, a4 = st.columns(4)
                pegel = zone.get(f"flug_tag_{jahr}")
                a1.metric(
                    f"Fluglärm tags ({jahr})",
                    f"{pegel:.0f} dB(A)" if pd.notna(pegel) else "unter 48 dB(A)",
                )
                brw = zone.get(f"bodenrichtwert_{jahr}")
                a2.metric(
                    f"Bodenrichtwert {jahr}",
                    f"{brw:,.0f} €/m²".replace(",", ".") if pd.notna(brw) else "—",
                )
                effekt = zone.get("effekt_prozent")
                a3.metric(
                    "Geschätzter Lärmeffekt",
                    f"{effekt:+.1f} %" if pd.notna(effekt) else "—",
                    help="Bodenwertunterschied gegenüber vergleichbaren Zonen unter 48 dB(A)",
                )
                a4.metric("Gemeinde", str(zone.get("gemeinde", "—")))

    if spalte not in gefiltert.columns:
        st.warning(f"Für diese Darstellung fehlen noch Daten ({spalte}).")
    else:
        verfuegbar = gefiltert[spalte].notna().sum()
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Zonen in Auswahl", f"{len(gefiltert):,}".replace(",", "."))
        k2.metric("davon mit Wert", f"{verfuegbar:,}".replace(",", "."))
        if f"bodenrichtwert_{jahr}" in gefiltert:
            k3.metric(
                f"Median Bodenrichtwert {jahr}",
                f"{gefiltert[f'bodenrichtwert_{jahr}'].median():,.0f} €/m²".replace(",", "."),
            )
        laerm_spalte = f"flug_tag_{jahr}"
        belastet = (
            gefiltert[laerm_spalte].notna().sum() if laerm_spalte in gefiltert else 0
        )
        k4.metric(
            f"Zonen in Lärmkonturen ({jahr})", f"{belastet:,}".replace(",", ".")
        )

        karte_obj = zeichne_karte(
            gefiltert, spalte, konfig["palette"], konfig["einheit"], auswahl, fundstelle
        )
        # get_root().render() liefert das fertige HTML-Dokument. Über
        # _repr_html_() käme die Notebook-Fassung mit einem zweiten,
        # verschachtelten iframe.
        st_html(karte_obj.get_root().render(), height=620, scrolling=False)
        st.caption(
            "Jede Fläche ist eine amtliche Bodenrichtwertzone. Mit dem Mauszeiger "
            "über eine Zone fahren zeigt alle Kennzahlen dazu. Gestrichelte Linien "
            "sind die Fluglärmkonturen 50/55/60/65 dB(A); der graue Marker ist der "
            "Flughafen. Die Farbskala ist auf das 2.–98. Perzentil gestutzt, damit "
            "einzelne Ausreißer die Abstufung nicht schlucken. Zonen ohne Wert "
            "bleiben ungefärbt."
        )

        if spalte == "brw_veraenderung_pct":
            st.info(
                "**Zur Prozentangabe:** Sie zeigt, um wie viel Prozent sich der "
                "Bodenrichtwert je m² zwischen dem 01.01.2024 und dem 01.01.2026 "
                "verändert hat — nicht den Preis selbst. Bei Wohnbauland liegt die "
                "Spanne zwischen −33 % und +55 %, der Median bei 0 %. Große "
                "Prozentwerte findest du fast nur außerhalb des Baulands: Wenn "
                "Ackerland von 0,85 € auf 7,70 € je m² neu bewertet wird, sind das "
                "über 800 % — bei kaum ins Gewicht fallenden Beträgen. Deshalb ist "
                "die Voreinstellung „Wohnbauland\"."
            )

with tab_modelle:
    st.subheader("Wie stark hängen Bodenwerte am Fluglärm?")
    haupt = modelle["A2"]
    kern = haupt["koeffizienten"][0]
    immo = kern["effekt_immobilie_prozent"]

    s1, s2, s3 = st.columns(3)
    s1.metric("Effekt je dB(A) auf den Bodenwert", f"{kern['effekt_bodenwert_prozent']:+.2f} %")
    s2.metric("≈ auf den Immobilienwert", f"{immo[0]:+.1f} bis {immo[1]:+.1f} %")
    s3.metric("p-Wert", f"{kern['p_wert']:.4f}")

    st.info(
        "**Warum zwei Zahlen?** Gemessen wird der reine Bodenwert. Da der Boden "
        "im Rhein-Main-Gebiet grob 30-50 % des Immobilienwerts ausmacht und das "
        "Gebäude selbst nicht leiser oder lauter wird, fällt der Effekt auf den "
        "Gesamtwert einer Immobilie entsprechend kleiner aus. Die "
        "Vergleichswerte aus der Literatur (0,5-1,3 % je dB) beziehen sich auf "
        "den Gesamtwert."
    )

    st.markdown("#### Modell A: Wertunterschied je Lärmklasse")
    st.caption(modelle["A"]["beschreibung"] + f"  ·  n = {modelle['A']['n']}, R² = {modelle['A']['r2']}")
    st.dataframe(koeffiziententabelle(modelle["A"]), use_container_width=True, hide_index=True)

    st.markdown("#### Wie stabil ist das Ergebnis?")
    st.caption(
        "Je mehr Lagefaktoren kontrolliert werden, desto kleiner wird der "
        "geschätzte Effekt. Das zeigt, wie stark Fluglärm mit Lagequalität "
        "verwoben ist — und warum die untersten Zeilen die belastbarsten sind."
    )
    vergleich = pd.DataFrame(modelle["spezifikationsvergleich"])
    vergleich.columns = ["Kontrollvariablen", "n", "R²", "Effekt je dB (%)", "p-Wert"]
    st.dataframe(vergleich, use_container_width=True, hide_index=True)

    if "N" in modelle:
        st.markdown("#### Nachtlärm: schädlicher, aber schwerer zu trennen")
        n2 = modelle["N2"]["koeffizienten"][0]
        st.caption(
            modelle["N"]["beschreibung"]
            + f"  ·  stetig: {n2['effekt_bodenwert_prozent']:+.2f} % je dB(A), p = {n2['p_wert']}"
        )
        st.dataframe(
            koeffiziententabelle(modelle["N"]), use_container_width=True, hide_index=True
        )
        if "TN" in modelle:
            korr = modelle["TN"].get("korrelation_tag_nacht")
            st.info(
                f"Je dB wirkt der Nachtpegel etwas stärker als der Tagespegel "
                f"({n2['effekt_bodenwert_prozent']:+.2f} % gegenüber "
                f"{modelle['A2']['koeffizienten'][0]['effekt_bodenwert_prozent']:+.2f} %) "
                "— das passt zur Lärmwirkungsforschung, die Nachtlärm als den "
                "schädlicheren Teil einstuft. Sauber trennen lassen sich beide "
                f"allerdings nicht: Sie korrelieren mit {korr}. Nimmt man sie "
                "gemeinsam ins Modell, verliert jeder für sich die Signifikanz."
            )

    if "M" in modelle:
        st.markdown("#### Gegenprobe mit einer ganz anderen Zielgröße: der Miete")
        m = modelle["M"]
        st.caption(m["beschreibung"] + f"  ·  n = {m['n']}, R² = {m['r2']}")
        koef = m["koeffizienten"][0]
        st.metric(
            "Effekt je dB(A) auf die Nettokaltmiete",
            f"{koef['effekt_miete_prozent']:+.2f} %",
            help=f"p = {koef['p_wert']}",
        )
        st.warning(
            "Hier zeigt sich **kein** Effekt. Das ist kein Gegenbeweis, sondern "
            "eine Frage der Auflösung: Die Zensus-Miete liegt nur im 1-km-Raster "
            "vor, während der Fluglärm zonenscharf variiert. Innerhalb einer "
            "Rasterzelle ist die Miete konstant, der Lärm aber nicht — das zieht "
            "den Koeffizienten systematisch gegen null."
        )

    st.markdown("#### Modell B: Panel mit Zonen-Fixe-Effekten")
    b = modelle["B"]
    st.caption(b["beschreibung"] + f"  ·  {b['zonen']} Zonen, davon {b['zonen_mit_laermvariation']} mit Pegeländerung")
    st.dataframe(koeffiziententabelle(b), use_container_width=True, hide_index=True)
    st.warning(
        "Dieses Modell nutzt nur Zonen, deren Pegel sich über die Zeit ändert — "
        "im Wesentlichen den Verkehrseinbruch 2020/21. Der Effekt ist klein und "
        "statistisch nicht gesichert. Das passt zur Theorie: eine erkennbar "
        "vorübergehende Lärmpause schlägt sich nicht in dauerhaften Bodenwerten "
        "nieder. Für den langfristigen Zusammenhang ist der Querschnitt aussagekräftiger."
    )

with tab_wandel:
    st.subheader("Hat sich der Zusammenhang nach den Routenänderungen verändert?")

    st.markdown("##### 1. Geänderte Abflugroute „Cindy S\" (seit 10.07.2025)")
    if "C" in modelle:
        c = modelle["C"]
        st.caption(
            c["beschreibung"]
            + f"  ·  {c['treatment_zonen']} Treatment-Zonen, {c['kontroll_zonen']} Kontrollzonen"
        )
        st.dataframe(koeffiziententabelle(c), use_container_width=True, hide_index=True)
    else:
        st.info(
            "Wird berechnet, sobald die Bodenrichtwerte zum Stichtag 01.01.2026 "
            "vollständig eingelesen sind."
        )
    st.markdown(
        "Die Route gilt seit dem 10. Juli 2025 im einjährigen Probebetrieb. "
        "Zusätzlich belastet werden Erzhausen, Egelsbach und der Norden von "
        "Darmstadt; entlastet wird die Südumfliegung über Mainz und Wiesbaden. "
        "Zwischen Inkrafttreten und dem Stichtag 01.01.2026 liegen nur rund "
        "sechs Monate — Bodenrichtwerte reagieren träge und werden von den "
        "Gutachterausschüssen geglättet. Ein Nullergebnis ist hier kein Beleg "
        "für Wirkungslosigkeit, sondern erwartbar."
    )

    st.divider()
    st.markdown("##### 2. Weiterentwickeltes Betriebskonzept (angekündigt 06.05.2026)")
    st.markdown(
        "Mehr Abflüge Richtung Nordwesten, betroffen wären vor allem Flörsheim "
        "und Hattersheim-Eddersheim. Umgesetzt wird frühestens 2028. Der "
        "aktuellste Bodenrichtwert-Stichtag ist der 01.01.2026 und liegt damit "
        "**vor** der Ankündigung — ein Ankündigungseffekt kann in diesen Daten "
        "noch gar nicht sichtbar sein."
    )
    if "D" in modelle:
        st.caption("Ausgangsmessung für spätere Stichtage:")
        st.dataframe(koeffiziententabelle(modelle["D"]), use_container_width=True, hide_index=True)
    st.info(
        "Der nächste Stichtag 01.01.2028 ist der erste, der einen "
        "Ankündigungseffekt zeigen könnte. Das Projekt ist so gebaut, dass die "
        "Auswertung dann per Skript wiederholbar ist."
    )

with tab_referenz:
    greix = lade_greix(_stand(RESULTS / "greix_referenz.json"))
    reihe = lade_greix_reihe(_stand(ROOT / "data" / "raw" / "greix_staedte.parquet"))

    st.subheader("Halten die Bodenwerte, was echte Kaufpreise sagen?")
    st.markdown(
        "Der **GREIX** des Kiel Instituts beruht auf notariell beurkundeten "
        "Kaufpreisen — also auf tatsächlich gezahlten Beträgen, quartalsweise "
        "und ungeglättet. Damit lässt sich prüfen, ob die Bodenrichtwerte das "
        "Marktgeschehen überhaupt abbilden."
    )

    ffm = pd.DataFrame(greix["frankfurt"]["perioden"])
    if not ffm.empty:
        anzeige = ffm.rename(
            columns={
                "zeitraum": "Stichtage",
                "marktjahre": "Marktjahre",
                "bodenrichtwert_wachstum_pct": "Bodenrichtwert (%)",
                "kaufpreis_wachstum_pct": "Kaufpreis (%)",
                "differenz_pp": "Differenz (pp)",
            }
        )
        st.dataframe(anzeige, use_container_width=True, hide_index=True)

    st.error(
        "**Der wichtigste Befund dieses Vergleichs:** Die Bodenrichtwerte "
        "hinken dem Markt um rund einen Zyklus hinterher. Den Preiseinbruch "
        "von 2023 — real gut 17 % — haben sie zum Stichtag 2024 schlicht nicht "
        "abgebildet; sie gaben erst zum Stichtag 2026 nach, als die "
        "Kaufpreise längst wieder stiegen. Für die Frage nach „Cindy S\" heißt "
        "das: Eine Routenänderung vom Juli 2025 kann im Stichtag 01.01.2026 "
        "praktisch nicht enthalten sein. Das ist keine Vermutung mehr, sondern "
        "an dieser Gegenüberstellung ablesbar."
    )

    st.markdown("#### Kaufpreisentwicklung Frankfurt")
    ffm_reihe = reihe[reihe["stadt"].str.contains("Frankfurt", na=False)]
    verlauf = (
        ffm_reihe.pivot_table(
            index="jahr", columns="objekttyp", values="preis_eur_qm", aggfunc="mean"
        )
    )
    st.line_chart(verlauf, height=280)
    st.caption(
        "Mittlerer Kaufpreis je m² Wohnfläche. Der Gipfel 2022, der Einbruch "
        "2023 und die Erholung ab 2024 sind hier unmittelbar sichtbar — in den "
        "Bodenrichtwerten sind sie es nicht."
    )

    st.markdown("#### Frankfurter Stadtviertel nach Lage zur Einflugschneise")
    gruppen = pd.DataFrame(greix["viertel_gegen_laerm"]["gruppen"])
    g_anzeige = gruppen.rename(
        columns={
            "lage": "Lage",
            "viertel_anzahl": "Viertel",
            "preis_mittel": "Ø Kaufpreis (€/m²)",
            "kauffaelle": "Kauffälle",
            "abstand_zu_abseits_pct": "Abstand zu „abseits\" (%)",
        }
    )
    st.dataframe(g_anzeige, use_container_width=True, hide_index=True)

    einzel = pd.DataFrame(greix["viertel_gegen_laerm"]["viertel"]).rename(
        columns={
            "viertel": "Viertel",
            "preis_eur_qm": "Kaufpreis (€/m²)",
            "veraenderung_pct": "Veränderung (%)",
            "kauffaelle": "Kauffälle",
            "lage": "Lage",
        }
    )
    with st.expander("Einzelne Viertel anzeigen"):
        st.dataframe(einzel, use_container_width=True, hide_index=True)

    st.warning(
        "**Vorsicht bei der Deutung:** Dieser Vergleich ist ein reiner "
        "Rohvergleich ohne Kontrollvariablen. Die Viertel in der "
        "Einflugschneise — der Frankfurter Westen und Süden — sind zugleich "
        "die industriell geprägten und zentrumsferneren Lagen. Die 21 % "
        "Preisabstand sind deshalb eine Obergrenze und nicht der Lärmeffekt "
        "selbst. Genau deshalb rechnet der Regressions-Tab mit "
        "Lagekontrollen — und kommt dort auf einen kleineren Wert. Was dieser "
        "Vergleich leistet: Er zeigt die Richtung unabhängig von den "
        "Bodenrichtwerten, an echten Kaufverträgen."
    )

with tab_daten:
    st.subheader("Woher die Daten kommen")
    st.markdown(
        """
| Größe | Quelle | Stand |
|---|---|---|
| Bodenrichtwerte | BORIS Hessen (HVBG), WFS-Dienst und WMS-Auskunft | Stichtage 01.01.2020 / 2022 / 2024 / 2026 |
| Fluglärmkonturen | Umwelt- und Nachbarschaftshaus, LAeq Tag/Nacht | Jahreswerte 2013–2024 |
| Straßen-, Schienen-, Industrielärm | HLNUG, EU-Umgebungslärmkartierung | 2022 |
| Lagefaktoren | OpenStreetMap via Overpass | laufend |

Alle Quellen sind kostenfrei und ohne Anmeldung nutzbar.
"""
    )

    st.subheader("Was dieses Tool nicht kann")
    st.markdown(
        """
- **Bodenwerte sind keine Kaufpreise.** Gemessen wird der Wert des Grundstücks,
  nicht der einer Immobilie. Gutachterausschüsse glätten die Werte, und sie
  gelten für ein normiertes Referenzgrundstück je Zone.
- **Der Lärm ist nur oberhalb von 48 dB(A) bekannt.** Darunter veröffentlicht
  niemand Konturen; alle leiseren Zonen bilden gemeinsam die Referenzgruppe.
- **Korrelation ist nicht Kausalität.** Fluglärm liegt dort, wo auch Industrie,
  Autobahnen und historisch günstigere Wohnlagen liegen. Der
  Spezifikationsvergleich zeigt, wie stark der geschätzte Effekt davon abhängt,
  welche Lagefaktoren man kontrolliert.
- **Für 2025 fehlen Lärmkonturen.** Die Wirkung von „Cindy S\" lässt sich
  deshalb noch nicht über gemessene Pegel abbilden, sondern nur über die
  betroffenen Gemeinden.
- **Rheinland-Pfalz fehlt.** Mainz liegt außerhalb von BORIS Hessen; die
  entlastete Westseite ist dadurch nur mit Wiesbaden vertreten.
"""
    )

    st.subheader("Datensatz herunterladen")
    export = gefiltert.drop(columns="geometry")
    st.download_button(
        "Aktuelle Auswahl als CSV",
        export.to_csv(index=False).encode("utf-8"),
        file_name="fluglaerm_bodenwerte.csv",
        mime="text/csv",
    )

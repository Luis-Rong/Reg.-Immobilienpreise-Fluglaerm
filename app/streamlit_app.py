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
import streamlit as st
from folium.plugins import Fullscreen
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

DARSTELLUNGEN = {
    "Fluglärm (Tagespegel)": {
        "spalte": "flug_tag_gefuellt_2024",
        "einheit": "dB(A)",
        "palette": "YlOrRd",
        "erklaerung": (
            "Dauerschallpegel tagsüber (6-22 Uhr) aus den Isophonenkarten des "
            "Umwelt- und Nachbarschaftshauses. Werte unter 48 dB(A) werden nicht "
            "veröffentlicht und sind hier als 44 dargestellt."
        ),
    },
    "Bodenrichtwert": {
        "spalte": "bodenrichtwert_2024",
        "einheit": "€/m²",
        "palette": "YlGnBu",
        "erklaerung": "Amtlicher Bodenrichtwert zum Stichtag 01.01.2024 (BORIS Hessen).",
    },
    "Geschätzter Lärmeffekt": {
        "spalte": "effekt_prozent",
        "einheit": "%",
        "palette": "RdYlGn",
        "erklaerung": (
            "Modellbasierter Bodenwertunterschied gegenüber sonst vergleichbaren "
            "Zonen unter 48 dB(A). Aus Modell A geschätzt, gilt je Lärmklasse."
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


def _farbskala(werte: pd.Series, palette: str, einheit: str):
    """Stufenskala aus den Daten ableiten.

    Quantile allein reichen nicht: beim Fluglärm tragen über drei Viertel der
    Zonen denselben Ersatzwert, wodurch die Klassengrenzen zusammenfallen.
    Deshalb werden Grenzen erst entdoppelt und notfalls linear aufgespannt.
    """
    endlich = werte.dropna()
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


def zeichne_karte(gdf: gpd.GeoDataFrame, spalte: str, palette: str, einheit: str) -> folium.Map:
    m = folium.Map(location=FRA, zoom_start=11, tiles="CartoDB positron")
    Fullscreen().add_to(m)

    daten = gdf[gdf[spalte].notna()].copy()
    if daten.empty:
        return m

    skala = _farbskala(daten[spalte], palette, einheit)

    def stil(feature):
        wert = feature["properties"].get(spalte)
        return {
            "fillColor": skala(wert) if wert is not None else "#cccccc",
            "color": "#555555",
            "weight": 0.3,
            "fillOpacity": 0.75,
        }

    tooltip_felder = ["gemeinde", "gemarkung", spalte]
    aliase = ["Gemeinde", "Gemarkung", f"Wert ({einheit})"]
    for extra, alias in (
        ("bodenrichtwert_2024", "Bodenrichtwert 2024 (€/m²)"),
        ("flug_tag_2024", "Fluglärm Tag (dB(A))"),
        ("klasse", "Lärmklasse"),
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
    return m


def koeffiziententabelle(modell: dict) -> pd.DataFrame:
    zeilen = []
    for k in modell["koeffizienten"]:
        sig = "ja" if k["signifikant_5pct"] else "nein"
        immo = k["effekt_immobilie_prozent"]
        zeilen.append(
            {
                "Merkmal": k["term"],
                "Effekt auf Bodenwert": f"{k['effekt_bodenwert_prozent']:+.1f} %",
                "95%-Konfidenzintervall": f"{k['ki_unten']:+.1f} bis {k['ki_oben']:+.1f} %",
                "p-Wert": f"{k['p_wert']:.4f}",
                "signifikant (5 %)": sig,
                "≈ Effekt auf Immobilienwert": f"{immo[0]:+.1f} bis {immo[1]:+.1f} %",
            }
        )
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

    nur_wohnen = st.checkbox("Nur Wohnbauland zeigen", value=True)
    gemeinden = sorted(karte["gemeinde"].dropna().unique())
    filter_gemeinde = st.multiselect("Auf Gemeinden eingrenzen", gemeinden)

    st.divider()
    st.caption(konfig["erklaerung"])

gefiltert = karte
if nur_wohnen:
    gefiltert = gefiltert[
        gefiltert["nutzung_gruppe"].eq("wohnen") & gefiltert["ist_bauland"]
    ]
if filter_gemeinde:
    gefiltert = gefiltert[gefiltert["gemeinde"].isin(filter_gemeinde)]

tab_karte, tab_modelle, tab_wandel, tab_daten = st.tabs(
    ["Karte", "Regressionsergebnisse", "Routenänderungen", "Daten & Grenzen"]
)

with tab_karte:
    spalte = konfig["spalte"]
    if spalte not in gefiltert.columns:
        st.warning(f"Für diese Darstellung fehlen noch Daten ({spalte}).")
    else:
        verfuegbar = gefiltert[spalte].notna().sum()
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Zonen in Auswahl", f"{len(gefiltert):,}".replace(",", "."))
        k2.metric("davon mit Wert", f"{verfuegbar:,}".replace(",", "."))
        if "bodenrichtwert_2024" in gefiltert:
            k3.metric(
                "Median Bodenrichtwert",
                f"{gefiltert['bodenrichtwert_2024'].median():,.0f} €/m²".replace(",", "."),
            )
        belastet = gefiltert["flug_tag_2024"].notna().sum() if "flug_tag_2024" in gefiltert else 0
        k4.metric("Zonen in Lärmkonturen", f"{belastet:,}".replace(",", "."))

        karte_obj = zeichne_karte(gefiltert, spalte, konfig["palette"], konfig["einheit"])
        # get_root().render() liefert das fertige HTML-Dokument. Über
        # _repr_html_() käme die Notebook-Fassung mit einem zweiten,
        # verschachtelten iframe.
        st_html(karte_obj.get_root().render(), height=620, scrolling=False)
        st.caption(
            "Gestrichelte Linien: Fluglärmkonturen 50/55/60/65 dB(A) des jüngsten "
            "verfügbaren Jahrgangs. Zonen ohne Wert bleiben ungefärbt."
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

"""Bodenrichtwerte gegen echte Kaufpreise halten.

Die gesamte Analyse steht und fällt damit, ob Bodenrichtwerte das
Marktgeschehen überhaupt abbilden. Sie werden von Gutachterausschüssen aus
Kaufverträgen abgeleitet, aber geglättet und nur alle zwei Jahre neu
festgesetzt. Der GREIX beruht auf denselben notariell beurkundeten
Kaufpreisen, erscheint jedoch quartalsweise und ungeglättet.

Verglichen werden deshalb die Wachstumsraten zwischen den Stichtagen -- und
zusätzlich das Preisniveau der Frankfurter Stadtviertel gegen ihre
Fluglärmbelastung.

Ergebnis: results/greix_referenz.json
"""

from __future__ import annotations

import json
import sys

import geopandas as gpd
import pandas as pd

from config import DATA_PROCESSED, DATA_RAW, RESULTS

# Die Windows-Konsole voreingestellt auf cp1252 scheitert an Zeichen wie "→".
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Der Bodenrichtwert zum 01.01.JJJJ spiegelt das Marktgeschehen des Vorjahres.
STICHTAG_ZU_MARKTJAHR = {2020: 2019, 2022: 2021, 2024: 2023, 2026: 2025}

# Zuordnung der GREIX-Stadtviertel zur Fluglärmlage. Die Namen sind
# GREIX-eigene Gebietszuschnitte; die Einordnung folgt der Lage relativ zur
# Ost-West-Anfluggrundlinie des Flughafens.
VIERTEL_LAGE = {
    "West-Autobahn": "in der Einflugschneise",
    "Süden": "in der Einflugschneise",
    "Nord-West": "randlich betroffen",
    "Osten": "randlich betroffen",
    "Mitte-West": "abseits",
    "Mitte-Nord": "abseits",
    "Norden": "abseits",
    "Bornheim-Ostend": "abseits",
    "Westend/Innenstadt": "abseits",
}


def brw_entwicklung(gemeinde: str) -> pd.Series:
    """Median-Bodenrichtwert für Wohnbauland je Stichtag."""
    zonen = gpd.read_parquet(DATA_PROCESSED / "zonen.parquet")
    panel = pd.read_parquet(DATA_PROCESSED / "panel.parquet")

    df = panel.merge(
        zonen[["gml_id", "gemeinde", "nutzung_gruppe", "ist_bauland"]], on="gml_id"
    )
    df = df[
        df["nutzung_gruppe"].eq("wohnen")
        & df["ist_bauland"]
        & df["gemeinde"].eq(gemeinde)
    ]
    return df.groupby("stichtag")["bodenrichtwert"].median()


def greix_jahreswerte(stadt: str) -> pd.DataFrame:
    """Jahresmittel der Kaufpreise je m² Wohnfläche."""
    df = pd.read_parquet(DATA_RAW / "greix_staedte.parquet")
    df = df[df["stadt"].str.contains(stadt, case=False, na=False)]
    return (
        df.groupby(["jahr", "objekttyp"])["preis_eur_qm"]
        .mean()
        .unstack()
        .assign(mittel=lambda d: d.mean(axis=1))
    )


def vergleiche(gemeinde: str, greix_stadt: str) -> dict:
    brw = brw_entwicklung(gemeinde)
    greix = greix_jahreswerte(greix_stadt)

    zeilen = []
    stichtage = sorted(brw.dropna().index)
    for frueher, spaeter in zip(stichtage, stichtage[1:]):
        markt_von, markt_bis = STICHTAG_ZU_MARKTJAHR[frueher], STICHTAG_ZU_MARKTJAHR[spaeter]
        if markt_von not in greix.index or markt_bis not in greix.index:
            continue

        brw_wachstum = (brw[spaeter] / brw[frueher] - 1) * 100
        greix_wachstum = (
            greix.loc[markt_bis, "mittel"] / greix.loc[markt_von, "mittel"] - 1
        ) * 100
        zeilen.append(
            {
                "zeitraum": f"{frueher} → {spaeter}",
                "marktjahre": f"{markt_von} → {markt_bis}",
                "bodenrichtwert_wachstum_pct": round(float(brw_wachstum), 1),
                "kaufpreis_wachstum_pct": round(float(greix_wachstum), 1),
                "differenz_pp": round(float(brw_wachstum - greix_wachstum), 1),
            }
        )
    return {"gemeinde": gemeinde, "greix_stadt": greix_stadt, "perioden": zeilen}


def viertel_gegen_laerm() -> dict:
    """Kaufpreisniveau der Frankfurter Viertel nach Fluglärmlage."""
    viertel = pd.read_parquet(DATA_RAW / "greix_viertel.parquet")
    viertel["lage"] = viertel["viertel"].map(VIERTEL_LAGE).fillna("unbekannt")

    gruppen = (
        viertel.groupby("lage")
        .agg(
            viertel_anzahl=("viertel", "size"),
            preis_mittel=("preis_eur_qm", "mean"),
            kauffaelle=("kauffaelle", "sum"),
        )
        .round(0)
        .reset_index()
    )

    abseits = gruppen.loc[gruppen["lage"].eq("abseits"), "preis_mittel"]
    for lage in gruppen["lage"]:
        maske = gruppen["lage"].eq(lage)
        gruppen.loc[maske, "abstand_zu_abseits_pct"] = round(
            float(
                (gruppen.loc[maske, "preis_mittel"].iloc[0] / abseits.iloc[0] - 1) * 100
            ),
            1,
        )

    return {
        "gruppen": gruppen.to_dict("records"),
        "viertel": viertel[["viertel", "preis_eur_qm", "veraenderung_pct", "kauffaelle"]]
        .assign(lage=viertel["lage"])
        .to_dict("records"),
    }


def main() -> None:
    ergebnis = {
        "beschreibung": (
            "GREIX-Kaufpreise (notariell beurkundet, EUR je m² Wohnfläche) als "
            "unabhängige Referenz zu den Bodenrichtwerten"
        ),
        "frankfurt": vergleiche("Frankfurt am Main", "Frankfurt"),
        "wiesbaden": vergleiche("Wiesbaden", "Wiesbaden"),
        "viertel_gegen_laerm": viertel_gegen_laerm(),
    }

    # Marktkontext für das Cindy-S-Fenster: Was taten echte Preise 2024-2026?
    greix = pd.read_parquet(DATA_RAW / "greix_staedte.parquet")
    ffm = greix[greix["stadt"].str.contains("Frankfurt", na=False)]
    fenster = ffm[
        ((ffm["jahr"] == 2024) & (ffm["quartal"] >= 3)) | (ffm["jahr"] >= 2025)
    ]
    ergebnis["marktkontext_2024_2026"] = {
        "quartale": int(fenster["periode"].nunique()),
        "kauffaelle_gesamt": int(fenster["kauffaelle"].fillna(0).sum()),
        "mittlere_quartalsveraenderung_pct": round(
            float(fenster["veraenderung_pct"].mean()), 2
        ),
    }

    (RESULTS / "greix_referenz.json").write_text(
        json.dumps(ergebnis, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print("Bodenrichtwerte gegen Kaufpreise, Frankfurt am Main:")
    for p in ergebnis["frankfurt"]["perioden"]:
        print(
            f"  {p['zeitraum']}  Bodenwert {p['bodenrichtwert_wachstum_pct']:+6.1f} %"
            f"   Kaufpreis {p['kaufpreis_wachstum_pct']:+6.1f} %"
            f"   Differenz {p['differenz_pp']:+6.1f} pp"
        )
    print("\nFrankfurter Viertel nach Fluglärmlage:")
    for g in ergebnis["viertel_gegen_laerm"]["gruppen"]:
        print(
            f"  {g['lage']:24s} n={int(g['viertel_anzahl'])}  "
            f"{g['preis_mittel']:.0f} EUR/m²  "
            f"({g['abstand_zu_abseits_pct']:+.1f} % gegenüber abseits)"
        )


if __name__ == "__main__":
    main()

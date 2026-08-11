"""GREIX-Kaufpreise als unabhängige Referenz zu den Bodenrichtwerten.

Der German Real Estate Index des Kiel Instituts und der Gutachterausschüsse
beruht auf notariell beurkundeten Kaufpreisen -- also auf tatsächlich
bezahlten Beträgen, nicht auf Angeboten und nicht auf gutachterlich
geglätteten Bodenwerten. Damit lässt sich prüfen, ob die
Bodenrichtwertentwicklung überhaupt zum echten Marktgeschehen passt.

Abgerufen werden Quartalswerte in EUR je m² Wohnfläche für Frankfurt und
Wiesbaden sowie den bundesweiten GREIX als Vergleichsmaßstab, dazu die
Frankfurter Stadtviertel.

Ergebnis:
  data/raw/greix_staedte.parquet   Stadt x Quartal x Objekttyp
  data/raw/greix_viertel.parquet   Frankfurter Viertel (Jahreswerte)
"""

from __future__ import annotations

import time

import pandas as pd
import requests

from config import DATA_RAW, REQUEST_DELAY_S, USER_AGENT

API = "https://api.greixx.net/api-v1"

# Städte im bzw. am Untersuchungsgebiet, plus den bundesweiten Index als
# Vergleichsmaßstab für die allgemeine Marktentwicklung.
STAEDTE = {"Frankfurt": 2, "Wiesbaden": 8, "GREIX (bundesweit)": 19}

OBJEKTTYPEN = {1: "Einfamilienhaus", 2: "Mehrfamilienhaus", 3: "Eigentumswohnung"}

VON_JAHR, BIS_JAHR = 2010, 2026

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT})


def _hole(pfad: str, params: dict) -> dict | list:
    resp = SESSION.get(f"{API}/{pfad}", params=params, timeout=120)
    resp.raise_for_status()
    return resp.json()


def fetch_staedte() -> pd.DataFrame:
    """Quartalsweise Kaufpreise je m² Wohnfläche.

    data_index=false liefert Preise in EUR/m² statt Indexpunkten,
    inflation=false die nominalen Werte -- passend zu den ebenfalls
    nominalen Bodenrichtwerten.
    """
    daten = _hole(
        "cities/metrics/",
        {
            "lng": "de",
            "cities": ",".join(str(i) for i in STAEDTE.values()),
            "prop_types": "1,2,3",
            "inflation": "false",
            "data_index": "false",
            "per_year": "false",
            "from_quarter": 1,
            "to_quarter": 4,
            "from_year": VON_JAHR,
            "to_year": BIS_JAHR,
        },
    )

    zeilen = []
    for typ_id, quartale in daten.get("chart_legend", {}).items():
        for quartal, staedte in quartale.items():
            for stadt, werte in staedte.items():
                if werte.get("data_value") is None:
                    continue
                q, jahr = quartal.split()
                zeilen.append(
                    {
                        "stadt": stadt,
                        "objekttyp": OBJEKTTYPEN.get(int(typ_id), typ_id),
                        "jahr": int(jahr),
                        "quartal": int(q.lstrip("Q")),
                        "preis_eur_qm": float(werte["data_value"]),
                        "veraenderung_pct": werte.get("data_growth_value"),
                        "kauffaelle": werte.get("no_obs"),
                        "baujahr_mittel": werte.get("avg_year_construction"),
                        "wohnflaeche_mittel": werte.get("avg_size"),
                    }
                )

    df = pd.DataFrame(zeilen)
    df["periode"] = df["jahr"].astype(str) + "-Q" + df["quartal"].astype(str)
    return df.sort_values(["stadt", "objekttyp", "jahr", "quartal"]).reset_index(drop=True)


def fetch_viertel() -> pd.DataFrame:
    """Preisniveau der Frankfurter Stadtviertel (Jahreswerte)."""
    liste = _hole("neighborhoods/", {"lng": "de", "city": STAEDTE["Frankfurt"]})
    namen = {
        n["id"]: n["name"]
        for n in liste
        if "frankfurt" in n["city"]["name"].lower()
    }

    karte = _hole("neighborhoods/map/", {"lng": "de", "city": STAEDTE["Frankfurt"]})
    zeilen = []
    for viertel_id, werte in karte.get("data", {}).items():
        zeilen.append(
            {
                "viertel_id": viertel_id,
                "viertel": namen.get(viertel_id, viertel_id[:8]),
                "preis_eur_qm": werte.get("value_price"),
                "veraenderung_pct": werte.get("value_growth"),
                "kauffaelle": werte.get("no_obs_sqm"),
            }
        )
    df = pd.DataFrame(zeilen)
    df["jahr_von"] = karte.get("year_min")
    df["jahr_bis"] = karte.get("year_max")
    return df.sort_values("preis_eur_qm", ascending=False).reset_index(drop=True)


def main() -> None:
    pfad_staedte = DATA_RAW / "greix_staedte.parquet"
    if not pfad_staedte.exists():
        df = fetch_staedte()
        df.to_parquet(pfad_staedte)
        print(f"greix_staedte: {len(df)} Zeilen, {df['stadt'].nunique()} Städte")
        for stadt, g in df.groupby("stadt"):
            letzte = g.sort_values(["jahr", "quartal"]).iloc[-1]
            print(
                f"  {stadt:22s} zuletzt {letzte['periode']}: "
                f"{letzte['preis_eur_qm']:.0f} EUR/m² ({letzte['objekttyp']})"
            )
        time.sleep(REQUEST_DELAY_S)
    else:
        print("greix_staedte.parquet existiert bereits -> übersprungen")

    pfad_viertel = DATA_RAW / "greix_viertel.parquet"
    if not pfad_viertel.exists():
        df = fetch_viertel()
        df.to_parquet(pfad_viertel)
        print(f"\ngreix_viertel: {len(df)} Frankfurter Viertel")
        print(df[["viertel", "preis_eur_qm", "veraenderung_pct", "kauffaelle"]].to_string(index=False))
    else:
        print("greix_viertel.parquet existiert bereits -> übersprungen")


if __name__ == "__main__":
    main()

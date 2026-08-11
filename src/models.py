"""Regressionsmodelle zum Zusammenhang von Fluglärm und Bodenwerten.

Geschätzt wird ein hedonisches Preismodell in halblogarithmischer Form: der
Koeffizient eines Lärmmaßes liest sich damit als prozentualer Wertunterschied.

Zwei Dinge sind bei der Interpretation entscheidend:

1. Die Zielgröße ist der Bodenrichtwert, also der reine Bodenwert. Da der
   Boden im Rhein-Main-Gebiet grob 30-50 % des Immobilienwerts ausmacht und
   das Gebäude vom Lärm unberührt bleibt, fällt ein Effekt auf den Bodenwert
   entsprechend größer aus als auf den Gesamtwert einer Immobilie. Die
   Literaturwerte von 0,5-1,3 % je dB beziehen sich auf den Gesamtwert.

2. Fluglärm ist räumlich mit Lagequalität verwoben. In Frankfurt liegen die
   lauteren Wohnlagen zugleich zentraler und sind deshalb roh betrachtet
   teurer. Ohne räumliche Kontrollen dreht sich das Vorzeichen. Deshalb wird
   jedes Modell zusätzlich in einem Spezifikationsvergleich gezeigt.

Ergebnis: results/modelle.json, results/zonen_effekt.parquet
"""

from __future__ import annotations

import json
import warnings

import geopandas as gpd
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

from config import (
    BETRIEBSKONZEPT_TREATMENT_GEMEINDEN,
    CINDY_S_TREATMENT_GEMEINDEN,
    DATA_PROCESSED,
    RESULTS,
)

warnings.filterwarnings("ignore", category=FutureWarning)

# Modellklassen gröber als die Kartenklassen: oberhalb von 60 dB(A) liegen im
# Wohnbauland nur zwei Zonen, eine eigene Klasse wäre nicht schätzbar.
MODELL_BINS = [0, 48, 50, 55, 200]
MODELL_LABELS = ["unter 48", "48-50", "50-55", "55 und mehr"]
REFERENZ = "unter 48"

# Anteil des Bodenwerts am Immobilienwert -- Spanne für die Umrechnung des
# Bodenwerteffekts in einen Effekt auf den Gesamtwert.
BODENWERTANTEIL = (0.30, 0.50)

DISTANZEN = "dist_bahn_km + dist_autobahn_km + dist_zentrum_km + dist_flughafen_km"
UMFELD = "anteil_industrie_1km + anteil_gruen_1km"
RAUMTREND = "x0 + y0 + I(x0**2) + I(y0**2) + x0:y0"
VOLL = f"{DISTANZEN} + strasse_g + {UMFELD} + {RAUMTREND}"


def lade_daten() -> pd.DataFrame:
    zonen = gpd.read_parquet(DATA_PROCESSED / "zonen.parquet")
    punkte = zonen.geometry.representative_point()
    zonen = zonen.drop(columns="geometry")
    zonen["x"] = punkte.x.values / 1000
    zonen["y"] = punkte.y.values / 1000

    panel = pd.read_parquet(DATA_PROCESSED / "panel.parquet")
    df = panel.merge(zonen, on="gml_id", how="left")

    df = df[df["nutzung_gruppe"].eq("wohnen") & df["ist_bauland"]]
    df = df[df["bodenrichtwert"].gt(0) & df["log_brw"].notna()].copy()

    # Straßenlärm fehlt außerhalb der kartierten Flächen -> unterhalb 40 dB(A)
    df["strasse_g"] = df["strasse_lden"].fillna(39.0)
    df["x0"] = df["x"] - df["x"].mean()
    df["y0"] = df["y"] - df["y"].mean()
    df["klasse"] = pd.cut(
        df["flug_tag_gefuellt"], bins=MODELL_BINS, labels=MODELL_LABELS, right=False
    ).astype(str)
    return df


def _fit(formel: str, daten: pd.DataFrame):
    return smf.ols(formel, data=daten).fit(
        cov_type="cluster", cov_kwds={"groups": daten["gemeinde"]}
    )


def _koeffizienten(modell, terme: list[str]) -> list[dict]:
    conf = modell.conf_int()
    out = []
    for term in terme:
        if term not in modell.params.index:
            continue
        b = float(modell.params[term])
        lo, hi = float(conf.loc[term, 0]), float(conf.loc[term, 1])
        effekt = (np.exp(b) - 1) * 100
        out.append(
            {
                "term": term.replace(f"C(klasse, Treatment(reference='{REFERENZ}'))[T.", "")
                .rstrip("]"),
                "koeffizient": round(b, 5),
                "effekt_bodenwert_prozent": round(effekt, 2),
                "ki_unten": round((np.exp(lo) - 1) * 100, 2),
                "ki_oben": round((np.exp(hi) - 1) * 100, 2),
                "std_fehler": round(float(modell.bse[term]), 5),
                "p_wert": round(float(modell.pvalues[term]), 4),
                "signifikant_5pct": bool(modell.pvalues[term] < 0.05),
                "effekt_immobilie_prozent": [
                    round(effekt * BODENWERTANTEIL[0], 2),
                    round(effekt * BODENWERTANTEIL[1], 2),
                ],
            }
        )
    return out


def modell_a(df: pd.DataFrame) -> tuple[dict, object, pd.DataFrame]:
    """Hauptmodell: Lärmklassen im Querschnitt 2024."""
    d = df[df["stichtag"] == 2024].copy()
    formel = (
        f"log_brw ~ C(klasse, Treatment(reference='{REFERENZ}')) + {VOLL} + C(gemeinde)"
    )
    m = _fit(formel, d)
    terme = [t for t in m.params.index if "klasse" in t]
    res = {
        "name": "A",
        "beschreibung": (
            "Querschnitt 2024: Lärmklassen gegenüber Zonen unter 48 dB(A), "
            "mit Distanz-, Straßenlärm-, Raumtrend- und Gemeinde-Kontrollen"
        ),
        "n": int(m.nobs),
        "r2": round(float(m.rsquared), 4),
        "koeffizienten": _koeffizienten(m, terme),
    }
    return res, m, d


def modell_a2(df: pd.DataFrame) -> dict:
    """Stetiger Pegeleffekt je dB."""
    d = df[df["stichtag"] == 2024].copy()
    m = _fit(f"log_brw ~ flug_tag_gefuellt + {VOLL} + C(gemeinde)", d)
    return {
        "name": "A2",
        "beschreibung": "Querschnitt 2024: stetiger Effekt je dB(A) Tagespegel",
        "n": int(m.nobs),
        "r2": round(float(m.rsquared), 4),
        "koeffizienten": _koeffizienten(m, ["flug_tag_gefuellt"]),
    }


def spezifikationsvergleich(df: pd.DataFrame) -> list[dict]:
    """Wie stabil ist der Effekt über verschiedene Kontrollsätze?"""
    d = df[df["stichtag"] == 2024].copy()
    varianten = {
        "ohne Kontrollen": "log_brw ~ flug_tag_gefuellt",
        "Distanzen": f"log_brw ~ flug_tag_gefuellt + {DISTANZEN} + strasse_g",
        "+ Umfeld (Industrie/Grün)": f"log_brw ~ flug_tag_gefuellt + {DISTANZEN} + strasse_g + {UMFELD}",
        "+ Raumtrend": f"log_brw ~ flug_tag_gefuellt + {DISTANZEN} + strasse_g + {UMFELD} + {RAUMTREND}",
        "+ Gemeinde-FE": f"log_brw ~ flug_tag_gefuellt + {DISTANZEN} + strasse_g + {UMFELD} + C(gemeinde)",
        "vollständig": f"log_brw ~ flug_tag_gefuellt + {VOLL} + C(gemeinde)",
    }
    out = []
    for name, formel in varianten.items():
        m = _fit(formel, d)
        b = float(m.params["flug_tag_gefuellt"])
        out.append(
            {
                "spezifikation": name,
                "n": int(m.nobs),
                "r2": round(float(m.rsquared), 4),
                "effekt_je_db_prozent": round((np.exp(b) - 1) * 100, 2),
                "p_wert": round(float(m.pvalues["flug_tag_gefuellt"]), 4),
            }
        )
    return out


def modell_b(df: pd.DataFrame) -> dict:
    """Panel mit Zonen- und Stichtags-Fixen-Effekten."""
    d = df.dropna(subset=["log_brw", "flug_tag_gefuellt"]).copy()
    vollstaendig = (
        d.groupby("gml_id")["stichtag"].transform("nunique") == d["stichtag"].nunique()
    )
    d = d[vollstaendig].copy()

    for col in ("log_brw", "flug_tag_gefuellt"):
        d[f"{col}_w"] = d[col] - d.groupby("gml_id")[col].transform("mean")
    d["jahr"] = d["stichtag"].astype(str)

    m = _fit("log_brw_w ~ flug_tag_gefuellt_w + C(jahr)", d)
    varianz = d.groupby("gml_id")["flug_tag_gefuellt"].std()
    return {
        "name": "B",
        "beschreibung": (
            "Panel 2020-2024 mit Zonen- und Stichtags-Fixen-Effekten; "
            "identifiziert wird nur aus Zonen, deren Pegel sich über die Zeit ändert"
        ),
        "n": int(m.nobs),
        "r2": round(float(m.rsquared), 4),
        "zonen": int(d["gml_id"].nunique()),
        "zonen_mit_laermvariation": int((varianz > 0).sum()),
        "koeffizienten": _koeffizienten(m, ["flug_tag_gefuellt_w"]),
    }


def modell_c(df: pd.DataFrame) -> dict | None:
    """Differenz-von-Differenzen zur Routenänderung 'Cindy S' (seit 07/2025)."""
    if 2026 not in set(df["stichtag"]):
        return None

    d = df[df["stichtag"].isin([2024, 2026])].copy()
    d = d[d.groupby("gml_id")["stichtag"].transform("nunique") == 2].copy()
    d["treat"] = d["gemeinde"].isin(CINDY_S_TREATMENT_GEMEINDEN).astype(int)
    d["nach"] = (d["stichtag"] == 2026).astype(int)

    m = _fit("log_brw ~ treat:nach + C(gml_id) + C(nach)", d)
    terme = [t for t in m.params.index if "treat" in t]
    return {
        "name": "C",
        "beschreibung": (
            "Differenz-von-Differenzen: Bodenwertentwicklung 2024->2026 in den von "
            "'Cindy S' zusätzlich belasteten Gemeinden gegenüber allen übrigen"
        ),
        "n": int(m.nobs),
        "r2": round(float(m.rsquared), 4),
        "treatment_zonen": int(d[d["treat"] == 1]["gml_id"].nunique()),
        "kontroll_zonen": int(d[d["treat"] == 0]["gml_id"].nunique()),
        "koeffizienten": _koeffizienten(m, terme),
    }


def modell_d(df: pd.DataFrame) -> dict | None:
    """Ankündigungseffekt des Betriebskonzepts (Mai 2026) -- explorativ."""
    if 2026 not in set(df["stichtag"]):
        return None

    d = df[df["stichtag"].isin([2024, 2026])].copy()
    d = d[d.groupby("gml_id")["stichtag"].transform("nunique") == 2].copy()
    d["treat"] = d["gemeinde"].isin(BETRIEBSKONZEPT_TREATMENT_GEMEINDEN).astype(int)
    d["nach"] = (d["stichtag"] == 2026).astype(int)

    m = _fit("log_brw ~ treat:nach + C(gml_id) + C(nach)", d)
    terme = [t for t in m.params.index if "treat" in t]
    return {
        "name": "D",
        "beschreibung": (
            "Explorativ: Bodenwertentwicklung 2024->2026 in Flörsheim und "
            "Hattersheim. Der Stichtag 01.01.2026 liegt VOR der Ankündigung vom "
            "06.05.2026 -- ein Ankündigungseffekt kann hier noch nicht sichtbar "
            "sein. Das Modell dient als Ausgangsmessung für spätere Stichtage."
        ),
        "n": int(m.nobs),
        "r2": round(float(m.rsquared), 4),
        "treatment_zonen": int(d[d["treat"] == 1]["gml_id"].nunique()),
        "koeffizienten": _koeffizienten(m, terme),
    }


def zonen_effekte(df: pd.DataFrame, fit_a, d_2024: pd.DataFrame) -> pd.DataFrame:
    """Modellbasierter Lärmeffekt je Zone für die Kartendarstellung."""
    effekte = {REFERENZ: 0.0}
    for term, b in fit_a.params.items():
        if "klasse" in term and "T." in term:
            effekte[term.split("T.")[1].rstrip("]")] = (np.exp(b) - 1) * 100

    out = d_2024[
        ["gml_id", "klasse", "flug_tag", "flug_tag_gefuellt", "bodenrichtwert", "gemeinde"]
    ].copy()
    out["effekt_prozent"] = out["klasse"].map(effekte)
    return out


def main() -> None:
    df = lade_daten()
    print(f"Analysestichprobe: {len(df)} Beobachtungen, {df['gml_id'].nunique()} Zonen")
    print(df[df.stichtag == 2024]["klasse"].value_counts().to_string())

    res_a, fit_a, d24 = modell_a(df)
    ergebnisse: dict[str, object] = {
        "A": res_a,
        "A2": modell_a2(df),
        "B": modell_b(df),
        "spezifikationsvergleich": spezifikationsvergleich(df),
    }
    for name, fn in (("C", modell_c), ("D", modell_d)):
        res = fn(df)
        if res:
            ergebnisse[name] = res
        else:
            print(f"Modell {name} übersprungen: Stichtag 2026 fehlt noch")

    ergebnisse["hinweise"] = {
        "zielgroesse": "Bodenrichtwert (reiner Bodenwert, EUR/m²)",
        "bodenwertanteil_annahme": list(BODENWERTANTEIL),
        "referenzklasse": REFERENZ,
        "laermmass": "LAeq Tag (06-22 Uhr), Isophonen des Umwelt- und Nachbarschaftshauses",
    }

    (RESULTS / "modelle.json").write_text(
        json.dumps(ergebnisse, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    zonen_effekte(df, fit_a, d24).to_parquet(RESULTS / "zonen_effekt.parquet")

    for key in ("A", "A2", "B", "C", "D"):
        r = ergebnisse.get(key)
        if not r:
            continue
        print(f"\n--- Modell {key} (n={r['n']}, R²={r['r2']})")
        for k in r["koeffizienten"]:
            stern = "*" if k["signifikant_5pct"] else " "
            print(
                f"  {stern} {k['term'][:30]:30s} Boden {k['effekt_bodenwert_prozent']:+7.2f}% "
                f"[{k['ki_unten']:+7.2f},{k['ki_oben']:+7.2f}]  p={k['p_wert']}"
            )
    print("\n--- Spezifikationsvergleich (Effekt je dB auf den Bodenwert)")
    for s in ergebnisse["spezifikationsvergleich"]:
        print(
            f"  {s['spezifikation']:26s} n={s['n']:5d} R²={s['r2']:.3f} "
            f"{s['effekt_je_db_prozent']:+6.2f}%  p={s['p_wert']}"
        )


if __name__ == "__main__":
    main()

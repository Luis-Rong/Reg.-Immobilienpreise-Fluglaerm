# Fluglärm und Immobilienwerte rund um den Frankfurter Flughafen

Ein interaktives Tool, das mit einer hedonischen Regression schätzt, wie stark
Fluglärm auf die Bodenwerte im Rhein-Main-Gebiet durchschlägt — und ob sich
dieser Zusammenhang seit den jüngsten Flugroutenänderungen verschoben hat.

Alle verwendeten Daten sind amtlich, kostenfrei und ohne Anmeldung abrufbar.
Die Beschaffung läuft vollständig über Skripte und ist damit reproduzierbar.

## Ergebnis in einem Absatz

Fluglärm senkt die Bodenwerte messbar. Im am besten kontrollierten Modell
kostet jedes zusätzliche dB(A) Tagespegel rund **2,4 % Bodenwert**
(p = 0,003). Weil der Boden im Rhein-Main-Gebiet nur etwa 30–50 % des
Immobilienwerts ausmacht und das Gebäude selbst vom Lärm unberührt bleibt,
entspricht das etwa **0,7–1,2 % je dB auf den Gesamtwert einer Immobilie** —
und damit genau dem Korridor, den die internationale Literatur für Flughäfen
ausweist (0,5–1,3 % je dB). Für die Routenänderung „Cindy S" (seit Juli 2025)
ist es dagegen schlicht noch zu früh: Zwischen Inkrafttreten und dem jüngsten
Bodenrichtwert-Stichtag liegen sechs Monate, und die Schätzung ist erwartungs-
gemäß nicht signifikant.

## Warum das Ergebnis nicht trivial ist

Fluglärm liegt nicht zufällig im Raum. Er konzentriert sich auf Korridore, in
denen auch Industrie, Autobahnen und Bahntrassen liegen — und in Frankfurt
liegen die lauteren Wohnlagen zugleich zentrumsnäher und sind deshalb *roh
betrachtet teurer*. Ohne räumliche Kontrollen misst man daher fast nichts. Wie
stark die Schätzung davon abhängt, welche Lagefaktoren man kontrolliert, zeigt
der Spezifikationsvergleich:

| Kontrollvariablen | Effekt je dB auf den Bodenwert | p | R² |
|---|---|---|---|
| keine | −0,8 % | 0,334 | 0,00 |
| Distanzen (Flughafen, Bahn, Autobahn, Zentrum) + Straßenlärm | −4,7 % | <0,001 | 0,53 |
| + Umfeld (Industrie-/Grünflächenanteil) | −4,2 % | <0,001 | 0,55 |
| + räumlicher Trend | −3,0 % | <0,001 | 0,60 |
| + Gemeinde-Fixe-Effekte | −2,2 % | 0,003 | 0,72 |
| **vollständig** | **−2,4 %** | **0,003** | **0,73** |

Die unteren Zeilen sind die belastbaren. Dass der Effekt bei mehr Kontrollen
schrumpft und sich dann bei gut −2 % stabilisiert, ist genau das erwartete
Muster: Ein Teil des rohen Zusammenhangs war Lage, nicht Lärm.

## Die Modelle im Einzelnen

**Modell A — Wertunterschied je Lärmklasse (Querschnitt 2024, n = 2.044, R² = 0,73)**

| Lärmklasse (LAeq Tag) | Bodenwert ggü. Zonen unter 48 dB(A) | 95 %-KI | p |
|---|---|---|---|
| 48–50 dB(A) | −1,0 % | −9,0 bis +7,8 % | 0,825 |
| 50–55 dB(A) | **−19,1 %** | −32,0 bis −3,7 % | **0,017** |
| 55 dB(A) und mehr | **−21,2 %** | −30,6 bis −10,6 % | **0,0002** |

Der Effekt setzt erst oberhalb von 50 dB(A) ein und wächst dann kaum weiter —
ein Schwellenmuster, das gut zur Lärmwirkungsforschung passt.

**Modell A2 — stetiger Effekt:** −2,35 % Bodenwert je dB(A) (p = 0,003).

**Modell B — Panel 2020–2026 mit Zonen-Fixen-Effekten:** −0,02 % je dB
(p = 0,945, nicht signifikant). Dieses Modell nutzt nur die 374 Zonen, deren
Pegel sich über die Zeit ändert — im Kern der Verkehrseinbruch 2020/21 und die
anschließende Erholung. Dass hier nichts herauskommt, ist kein Widerspruch,
sondern ökonomisch plausibel: Eine erkennbar vorübergehende Lärmpause
kapitalisiert sich nicht in dauerhaften Bodenwerten. Der Querschnitt misst den
langfristig eingepreisten Zustand, das Panel die kurzfristige Reaktion.

## Haben die Routenänderungen etwas verändert?

**Modell C — „Cindy S", seit 10.07.2025 im einjährigen Probebetrieb.**
Zusätzlich belastet werden Erzhausen, Egelsbach und Darmstadt-Nord; entlastet
wird die Südumfliegung über Mainz und Wiesbaden. Differenz-von-Differenzen für
die Stichtage 2024 → 2026, 119 Treatment- gegen 1.813 Kontrollzonen:
**+2,5 %** (95 %-KI −0,7 bis +5,7 %, p = 0,123) — **kein signifikanter
Effekt**. Der jüngste Stichtag ist der 01.01.2026 und erfasst damit gerade
einmal sechs Monate nach der Änderung. Bodenrichtwerte werden von
Gutachterausschüssen aus Kaufverträgen abgeleitet und geglättet; sie reagieren
träge. Ein Nullergebnis ist hier erwartbar und kein Beleg für Wirkungslosigkeit.

**Modell D — Weiterentwickeltes Betriebskonzept, angekündigt am 06.05.2026.**
Mehr Abflüge Richtung Nordwesten, betroffen wären vor allem Flörsheim und
Hattersheim-Eddersheim; umgesetzt frühestens 2028. Ergebnis: +1,9 %
(p = 0,225). Das ist **ausdrücklich kein Ankündigungseffekt** — der Stichtag
01.01.2026 liegt *vor* der Ankündigung, ein solcher Effekt kann in diesen Daten
gar nicht enthalten sein. Das Modell dient als Ausgangsmessung; der Stichtag
01.01.2028 ist der erste, an dem sich etwas zeigen könnte.

## Datenquellen

| Größe | Quelle | Zugang | Stand |
|---|---|---|---|
| Bodenrichtwerte | BORIS Hessen (HVBG) | WFS für 2020/2022/2024, WMS-Auskunft für 2026 | Stichtage 01.01. |
| Fluglärmkonturen | Umwelt- und Nachbarschaftshaus | ArcGIS FeatureServer | Jahreswerte 2013–2024 |
| Straßen-, Schienen-, Industrielärm | HLNUG, EU-Umgebungslärmkartierung | ArcGIS MapServer (Raster) | 2022 |
| Lagefaktoren, Flächennutzung | OpenStreetMap | Overpass API | laufend |

Drei Fundstücke, die das Projekt erst möglich gemacht haben:

* Für den Stichtag **01.01.2026 gibt es keinen WFS** — der `/basis/`-Endpunkt
  von BORIS Hessen liefert null Features. Die Werte stecken aber im WMS-Layer
  `hboris_feature` und lassen sich per `GetFeatureInfo` an den
  Repräsentativpunkten der 2024er-Zonen auslesen.
* Die **EU-Umgebungslärmkartierung schneidet bei 55 dB(A) ab** und deckt damit
  nur 621 Zonen ab. Die Isophonen des Umwelt- und Nachbarschaftshauses beginnen
  dagegen bei 48 dB(A) (tags) bzw. 43 dB(A) (nachts) und liegen jahresweise
  vor — daraus wird überhaupt erst ein Panel.
* Die HLNUG-Rasterdienste **verwerfen Punkte außerhalb der Rasterausdehnung
  stillschweigend**, statt sie als „NoData" zurückzugeben. Wer die Abfrage
  bündelt, ohne vorher auf die Ausdehnung zu filtern, bekommt eine um Zeilen
  verschobene und damit falsche Zuordnung.

## Aufbau

```
src/
  config.py           Untersuchungsgebiet, Endpunkte, Treatment-Definitionen
  fetch_boris.py      Bodenrichtwerte: WFS (2020-2024) + WMS-Punktabfrage (2026)
  fetch_contours.py   Jährliche Fluglärm-Isophonen des UNH
  fetch_noise.py      EU-Umgebungslärmkartierung (Straße, Schiene, Industrie)
  fetch_controls.py   OSM: Distanzen, Industrie- und Grünflächenanteile
  build_dataset.py    Räumliche Verknüpfung zum Standort-Panel
  models.py           Hedonische Regressionen A, A2, B, C, D
  viz_prep.py         Kartendaten vereinfachen und exportieren
app/
  streamlit_app.py    Interaktive Karte, Ergebnistabellen, Limitationen
```

## Nachvollziehen

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
```

```bash
cd src && python fetch_boris.py && python fetch_contours.py && python fetch_noise.py && python fetch_controls.py && python build_dataset.py && python models.py && python viz_prep.py
```

```bash
streamlit run app/streamlit_app.py
```

Der vollständige Datenabruf dauert etwa eine Stunde; der größte Teil davon
entfällt auf die rund 5.400 Einzelabfragen für den Stichtag 2026. Alle Skripte
überspringen bereits vorhandene Dateien, sind also gefahrlos wiederholbar. Für
den Start der App genügen die im Repo enthaltenen aufbereiteten Dateien.

## Methodische Entscheidungen

* **Standort-Panel statt Zonen-Panel.** Die BORIS-Zonenzuschnitte ändern sich
  zwischen den Stichtagen, und die Zonen-IDs sind nicht stabil — die
  Schnittmenge der IDs von 2022 und 2024 ist leer. Verfolgt wird deshalb der
  Ort: Referenz sind die Zonen von 2024, für jeden anderen Stichtag wird der
  Wert der Zone übernommen, die den Repräsentativpunkt enthält.
* **Abgleich der Nutzungsart bei jedem Stichtag.** Verschieben sich Zonen-
  grenzen, kann ein Punkt, der 2024 in einer Wohnbauzone lag, 2026 in einer
  Landwirtschaftsfläche liegen. Ohne Prüfung entstehen daraus Scheinänderungen
  von mehreren tausend Prozent (Ackerland zu 0,70 €/m² gegen Bauland zu
  350 €/m²). Solche Treffer werden verworfen — je Stichtag rund 110 von 2.044.
* **Lärm aus dem Vorjahr.** Der Bodenrichtwert zum 01.01.2024 spiegelt das
  Marktgeschehen von 2023, ihm werden deshalb die 2023er Konturen zugeordnet.
* **Uneinheitliche Nutzungsschlüssel.** Frankfurt und Darmstadt verschlüsseln
  Wohnbauland als `W`, Wiesbaden nach BauNVO als `WR`/`WA`. Wer nur auf `W`
  filtert, verliert ganze Städte — die Klassifikation in `config.py` fängt das
  ab.
* **Geclusterte Standardfehler** auf Gemeindeebene, weil Bodenrichtwerte
  innerhalb einer Gemeinde vom selben Gutachterausschuss stammen.

## Grenzen

* **Bodenwerte sind keine Kaufpreise.** Gemessen wird der Wert des Grundstücks
  für ein normiertes Referenzgrundstück je Zone, nicht der einer konkreten
  Immobilie. Die Umrechnung auf den Immobilienwert beruht auf einer
  angenommenen Bodenwertquote von 30–50 %.
* **Unterhalb von 48 dB(A) ist der Lärm unbekannt.** Alle leiseren Zonen bilden
  gemeinsam die Referenzgruppe; ein Gradient im unteren Bereich lässt sich
  nicht schätzen.
* **Korrelation ist nicht Kausalität.** Der Spezifikationsvergleich legt offen,
  wie stark die Schätzung von den Kontrollvariablen abhängt. Nicht kontrolliert
  sind Sozialstruktur und Baualtersklassen.
* **Für 2025 fehlen Lärmkonturen.** Die Wirkung von „Cindy S" lässt sich
  deshalb nicht über gemessene Pegel abbilden, sondern nur über die betroffenen
  Gemeinden.
* **Rheinland-Pfalz fehlt.** Mainz liegt außerhalb von BORIS Hessen; die
  entlastete Westseite ist nur mit Wiesbaden vertreten.

## Lizenzhinweise

Bodenrichtwerte und Geobasisdaten: © HVBG, kostenfrei nutzbar nach § 1 Abs. 2
Gutachterausschusskostengesetz. Umgebungslärmkartierung: © HLNUG.
Fluglärmkonturen: © Gemeinnützige Umwelthaus GmbH. Kartendaten: ©
OpenStreetMap-Mitwirkende (ODbL).

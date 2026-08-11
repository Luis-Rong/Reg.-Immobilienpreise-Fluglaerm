# Fluglärm und Immobilienwerte rund um den Frankfurter Flughafen

Ein interaktives Tool, das mit einer hedonischen Regression schätzt, wie stark
Fluglärm auf die Bodenwerte im Rhein-Main-Gebiet durchschlägt — und ob sich
dieser Zusammenhang seit den jüngsten Flugroutenänderungen verschoben hat.

Alle verwendeten Daten sind amtlich, kostenfrei und ohne Anmeldung abrufbar.
Die Beschaffung läuft vollständig über Skripte und ist damit reproduzierbar.

## Ergebnis in einem Absatz

Fluglärm senkt die Bodenwerte messbar, aber weniger dramatisch als die rohen
Zahlen zunächst nahelegen. Im am besten kontrollierten Modell kostet jedes
zusätzliche dB(A) Tagespegel rund **3 % Bodenwert** (p = 0,04). Weil der Boden
im Rhein-Main-Gebiet nur etwa 30–50 % des Immobilienwerts ausmacht, entspricht
das etwa **0,9–1,5 % je dB auf den Gesamtwert einer Immobilie** — und damit
genau dem Korridor, den die internationale Literatur für Flughäfen ausweist
(0,5–1,3 % je dB). Für die Routenänderung „Cindy S" (seit Juli 2025) ist es
für eine belastbare Aussage schlicht noch zu früh: zwischen Inkrafttreten und
dem jüngsten Bodenrichtwert-Stichtag liegen nur sechs Monate.

## Warum das Ergebnis nicht trivial ist

Fluglärm liegt nicht zufällig im Raum. Er konzentriert sich auf Korridore, in
denen auch Industrie, Autobahnen und Bahntrassen liegen — und in Frankfurt
liegen die lauteren Wohnlagen zugleich zentrumsnäher und sind deshalb *roh
betrachtet teurer*. Ohne räumliche Kontrollen dreht sich das Vorzeichen also
sogar um. Wie stark die Schätzung davon abhängt, welche Lagefaktoren man
kontrolliert, zeigt der Spezifikationsvergleich:

| Kontrollvariablen | Effekt je dB auf den Bodenwert | p | R² |
|---|---|---|---|
| keine | −3,3 % | 0,102 | 0,00 |
| Distanzen (Flughafen, Bahn, Autobahn, Zentrum) + Straßenlärm | −8,1 % | <0,001 | 0,23 |
| + Umfeld (Industrie-/Grünflächenanteil) | −6,7 % | <0,001 | 0,27 |
| + räumlicher Trend | −3,0 % | 0,041 | 0,36 |
| + Gemeinde-Fixe-Effekte | −2,7 % | 0,115 | 0,46 |
| **vollständig** | **−3,0 %** | **0,043** | **0,47** |

Die Zeilen unten sind die belastbaren. Dass der Effekt bei mehr Kontrollen
schrumpft und sich dann bei rund −3 % stabilisiert, ist genau das erwartete
Muster: Ein Teil des rohen Zusammenhangs war Lage, nicht Lärm.

## Die Modelle im Einzelnen

**Modell A — Wertunterschied je Lärmklasse (Querschnitt 2024, n = 2.044)**

| Lärmklasse (LAeq Tag) | Bodenwert ggü. Zonen unter 48 dB(A) | 95 %-KI | p |
|---|---|---|---|
| 48–50 dB(A) | +30,1 % | −13,3 bis +95,2 % | 0,204 |
| 50–55 dB(A) | **−25,2 %** | −39,7 bis −7,2 % | **0,008** |
| 55 dB(A) und mehr | −26,3 % | −62,2 bis +43,8 % | 0,371 |

Nur die mittlere Klasse ist statistisch gesichert. Die oberste Klasse umfasst
lediglich 37 Zonen, die unterste ist vermutlich noch von Zentrumsnähe
überlagert — ein ehrlicher Hinweis darauf, dass die Klassenschätzung an den
Rändern dünn wird.

**Modell A2 — stetiger Effekt:** −3,03 % Bodenwert je dB(A) (p = 0,043).

**Modell B — Panel 2020–2024 mit Zonen-Fixen-Effekten:** −0,50 % je dB
(p = 0,505, nicht signifikant). Dieses Modell nutzt nur Zonen, deren Pegel sich
über die Zeit ändert — im Kern den Verkehrseinbruch 2020/21 und die
anschließende Erholung. Dass hier nichts herauskommt, ist kein Widerspruch,
sondern ökonomisch plausibel: Eine erkennbar vorübergehende Lärmpause
kapitalisiert sich nicht in dauerhaften Bodenwerten. Der Querschnitt misst den
langfristig eingepreisten Zustand, das Panel die kurzfristige Reaktion.

**Modelle C und D — Routenänderungen:** siehe unten.

## Haben die Routenänderungen etwas verändert?

**„Cindy S", seit 10.07.2025 im einjährigen Probebetrieb.** Zusätzlich belastet
werden Erzhausen, Egelsbach und Darmstadt-Nord; entlastet wird die
Südumfliegung über Mainz und Wiesbaden. Der jüngste Bodenrichtwert-Stichtag ist
der 01.01.2026 — er erfasst also gerade einmal sechs Monate nach der Änderung.
Bodenrichtwerte werden von Gutachterausschüssen aus Kaufverträgen abgeleitet
und geglättet; sie reagieren träge. Ein Nullergebnis ist hier zu erwarten und
wäre kein Beleg für Wirkungslosigkeit.

**Weiterentwickeltes Betriebskonzept, angekündigt am 06.05.2026.** Mehr Abflüge
Richtung Nordwesten, betroffen wären vor allem Flörsheim und
Hattersheim-Eddersheim; umgesetzt frühestens 2028. Der Stichtag 01.01.2026
liegt **vor** dieser Ankündigung — ein Ankündigungseffekt kann in diesen Daten
noch gar nicht enthalten sein. Das Projekt liefert dafür die Ausgangsmessung;
der Stichtag 01.01.2028 ist der erste, an dem sich etwas zeigen könnte.

## Datenquellen

| Größe | Quelle | Zugang | Stand |
|---|---|---|---|
| Bodenrichtwerte | BORIS Hessen (HVBG) | WFS für 2020/2022/2024, WMS-Auskunft für 2026 | Stichtage 01.01. |
| Fluglärmkonturen | Umwelt- und Nachbarschaftshaus | ArcGIS FeatureServer | Jahreswerte 2013–2024 |
| Straßen-, Schienen-, Industrielärm | HLNUG, EU-Umgebungslärmkartierung | ArcGIS MapServer (Raster) | 2022 |
| Lagefaktoren, Flächennutzung | OpenStreetMap | Overpass API | laufend |

Zwei Fundstücke, die das Projekt erst möglich gemacht haben:

* Für den Stichtag **01.01.2026 gibt es keinen WFS** — der `/basis/`-Endpunkt
  von BORIS Hessen liefert null Features. Die Werte stecken aber im
  WMS-Layer `hboris_feature` und lassen sich per `GetFeatureInfo` an den
  Repräsentativpunkten der 2024er-Zonen auslesen.
* Die **EU-Umgebungslärmkartierung schneidet bei 55 dB(A) ab** und deckt damit
  nur 621 Zonen ab. Die Isophonen des Umwelt- und Nachbarschaftshauses beginnen
  dagegen bei 48 dB(A) (tags) bzw. 43 dB(A) (nachts) und liegen jahresweise
  vor — daraus wird überhaupt erst ein Panel.

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

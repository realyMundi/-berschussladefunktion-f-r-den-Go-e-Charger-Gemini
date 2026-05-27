# go-e Überschussladen mit SMA + BYD in Home Assistant

PV-Überschussladen für **go-e Gemini Flex** mit **SMA Sunny Hybrid Wechselrichter** und **BYD HVS Batteriespeicher** via Home Assistant pyscript.

Das Skript löst ein konkretes Problem: Der go-e Charger sieht im ECO-Modus nur den Netzwert vom Stromzähler — und der lügt, wenn der BYD-Speicher gerade lädt oder entlädt. Das Skript berechnet den echten PV-Überschuss und übergibt ihn korrekt an die Wallbox. Außerdem verhindert es Netzbezug wenn der SMA-Wechselrichter sein AC-Limit erreicht.

## Funktionen

- **BYD-Korrektur**: Speicher-Ladung und -Entladung werden aus dem Netzwert herausgerechnet, damit der go-e den echten PV-Überschuss sieht
- **SMA AC-Limiter-Schutz**: Verhindert Netzbezug wenn Wechselrichter und Haus zusammen das AC-Limit des SMA erreichen
- **Intelligente Phasenwahl**: Beim Anstecken wird anhand des 5-Minuten-Durchschnitts automatisch 1P oder 3P gewählt
- **Fahrzeugprofile**: Verschiedene Mindestströme und Phasenschwellen je nach Fahrzeug
- **Zielwert Netz**: Schieberegler in HA steuert wie aggressiv geladen wird
- **Basic-Modus**: Im go-e Basic-Modus greift das Skript nicht in die Phasenwahl ein — manuelle Steuerung bleibt erhalten

## Voraussetzungen

### Hardware
- go-e Gemini Flex Wallbox (Firmware ≥ 59.4), via **MQTT** in HA eingebunden
- SMA Sunny Hybrid Wechselrichter, via **SMA Energy Meter / Modbus** in HA eingebunden
- BYD HVS Batteriespeicher (am SMA angeschlossen, Werte kommen vom SMA)

### Software
- Home Assistant mit installiertem **[pyscript](https://github.com/custom-components/pyscript)** (≥ v1.7.0)
- go-e in HA über **MQTT** eingebunden (nicht nur Cloud)
- Die Wallbox muss sich im **selben lokalen Netzwerk** befinden wie Home Assistant — das Skript steuert die Wallbox direkt per HTTP an ihre lokale IP (kein Cloud-Umweg, dadurch schneller und zuverlässiger)

### go-e App (einmalig einstellen)
Diese Einstellungen müssen **vor** dem ersten Start in der go-e App gesetzt werden:

| Einstellung | Wert | Hinweis |
|---|---|---|
| Lademodus | ECO | Pflicht für Überschussladen |
| PV-Überschuss-Modus (`fup`) | ✅ aktiv | |
| Cloud-Daten akzeptieren (`acp`) | ✅ aktiv | Damit go-e externe pGrid-Werte annimmt |
| Awattar-Fallback (`awe`) | ❌ deaktiviert | |
| Preisgrenze | -99 ct | Verhindert ungewollten Awattar-Fallback |
| Phasenumschaltverzögerung | 10 Minuten | Verhindert ständiges Umschalten |
| go-e Controller | ❌ deaktiviert | Konflikt mit diesem Skript |
| force_state | Neutral | **Niemals ändern!** |

> **Hinweis**: Der Status "Fallback (günstiger Strompreis)" bedeutet **nicht** Awattar-Fallback — er zeigt nur an, dass der go-e auf mehr PV-Überschuss wartet.

---

## Installation

### Schritt 1 – pyscript installieren

In Home Assistant: **HACS → Integrationen → pyscript** suchen und installieren.

Dann in `configuration.yaml` aktivieren:

```yaml
pyscript:
  allow_all_imports: true
  hass_is_global: true
```

Nach der Änderung HA neu starten.

### Schritt 2 – HA-Helfer anlegen

Die folgenden Helfer werden vom Skript benötigt. Am einfachsten direkt in `configuration.yaml` einfügen (Inhalt von `helpers.yaml` kopieren), oder den Inhalt von `helpers.yaml` in eine separate Datei auslagern.

**Entitäts-IDs** (werden im Skript als Konstanten referenziert):

| Entität | Typ | Zweck |
|---|---|---|
| `input_select.wallbox_fahrzeug` | Dropdown | Fahrzeugprofil wählen (Mindeststrom, Phasenschwelle) |
| `input_number.wallbox_zielwert_netz` | Schieberegler | Puffer zur Netzeinspeisung (-500 bis -50 W) |

Inhalt aus `helpers.yaml` in `configuration.yaml` einfügen:

> **Hinweis**: Falls du `input_select` oder `input_number` bereits in deiner `configuration.yaml` hast, füge die Helfer einfach unter den bestehenden Block ein — nicht den Block-Header (`input_select:`) doppelt anlegen, das führt zu einem „Duplicate Key Error" beim HA-Start.

```yaml
input_select:
  wallbox_fahrzeug:
    name: "Wallbox Fahrzeug"
    options:
      - "MG4"
      - "Twingo"
    initial: "MG4"
    icon: mdi:car-electric

input_number:
  wallbox_zielwert_netz:
    name: "Wallbox Zielwert Netz"
    min: -500
    max: -50
    step: 50
    initial: -200
    unit_of_measurement: "W"
    icon: mdi:transmission-tower
    mode: slider
```

Nach der Änderung HA neu starten.

### Schritt 3 – Sensor-IDs herausfinden

Das Skript benötigt die genauen Entitäts-IDs aus HA. Diese enthalten die Seriennummern der Geräte und müssen angepasst werden.

**SMA-Sensoren** finden: In HA unter *Einstellungen → Geräte & Dienste → SMA* das Gerät öffnen. Folgende Sensoren werden benötigt:

| Konstante im Skript | Gesuchter Sensor |
|---|---|
| `SENSOR_PV_POWER` | PV-Leistung (W) |
| `SENSOR_GRID_ABSORBED` | Netzbezug (W, immer ≥ 0) |
| `SENSOR_GRID_SUPPLIED` | Netzeinspeisung (W, immer ≥ 0) |
| `SENSOR_BAT_CHARGE` | Batterieladeleistung (W, immer ≥ 0) |
| `SENSOR_BAT_DISCHARGE` | Batterieentladeleistung (W, immer ≥ 0) |

**go-e Sensoren** finden: In HA unter *Einstellungen → Geräte & Dienste → go-e* das Gerät öffnen:

| Konstante im Skript | Gesuchter Sensor / Entität |
|---|---|
| `SENSOR_CHARGER_POWER` | Gesamtleistung Wallbox (W) |
| `SENSOR_CAR_STATE` | Fahrzeugstatus (Idle / Charging / WaitCar / Complete) |
| `SENSOR_CURRENT_L1` | Strom L1 (A) |
| `SENSOR_CURRENT_L2` | Strom L2 (A) |
| `SENSOR_CURRENT_L3` | Strom L3 (A) |
| `NUMBER_MAX_AMP` | Maximaler Ladestrom (A) — Number-Entität |
| `SELECT_LOGIC_MODE` | Lademodus (Eco / Default / NextTrip) — Select-Entität |

### Schritt 4 – Skript anpassen

Datei `smart_pv_charge.py` öffnen und den Abschnitt **KONFIGURATION** anpassen:

```python
# IP-Adresse der Wallbox im Heimnetz
GOE_IP = "192.168.178.98"   # ← eigene IP eintragen

# AC-Limit des Wechselrichters anpassen
# Richtwert: ~98% der Nennleistung
SMA_MAX_AC_W = 9800   # 10 kWp → 9800W
# SMA_MAX_AC_W = 6860  # 7 kWp
# SMA_MAX_AC_W = 4900  # 5 kWp
```

Dann im Abschnitt **ENTITÄTEN** die gefundenen Sensor-IDs aus Schritt 3 eintragen:

```python
SENSOR_PV_POWER      = "sensor.sn_XXXXXXXXXX_pv_power"          # ← anpassen
SENSOR_GRID_ABSORBED = "sensor.sn_XXXXXXXXXX_metering_power_absorbed"
# ... usw.

SENSOR_CHARGER_POWER = "sensor.go_echarger_XXXXXX_power_total"  # ← anpassen
# ... usw.
```

### Schritt 5 – Eigene Fahrzeuge eintragen

Im Skript im Abschnitt **FAHRZEUGPROFILE** eigene Fahrzeuge ergänzen:

```python
FAHRZEUG_PROFILE = {
    "MeinAuto": {"mca": 6, "schwelle_3p": -4340},
    # mca = Mindeststrom aus dem Fahrzeughandbuch (A)
    # schwelle_3p = -(mca × 3 × 230) - 200
    #   Beispiel 6A: -(6 × 3 × 230) - 200 = -4340W
}
```

Den gleichen Namen auch in `helpers.yaml` unter `options:` eintragen.

### Schritt 6 – Skript kopieren und laden

Datei nach `/config/pyscript/smart_pv_charge.py` kopieren.

In HA: *Einstellungen → Entwicklerwerkzeuge → Dienste* → `pyscript.reload` aufrufen, oder HA neu starten.

### Schritt 7 – Prüfen ob es läuft

In HA: *Einstellungen → System → Protokoll* aufrufen und nach `[Wallbox]` filtern. Alle 5 Sekunden sollte eine Zeile wie diese erscheinen:

```
[Wallbox] V4.2 | send=+123W echt=-456W avg=-380W/60 byd+0/-0W pv=4200W | car=3500W 3P max=16A haus=750W | MG4 pgt=-200W psm=0 | Charging
```

---

## Anpassung für andere Hardware

### Anderer Wechselrichter (kein SMA)

Das Skript benötigt fünf Werte vom Wechselrichter/Energiemessgerät:

| Wert | Beschreibung | Vorzeichen |
|---|---|---|
| PV-Leistung | Aktuelle Erzeugung | immer ≥ 0 |
| Netzbezug | Strom aus dem Netz | immer ≥ 0 (getrennt von Einspeisung!) |
| Netzeinspeisung | Strom ins Netz | immer ≥ 0 (getrennt von Bezug!) |
| Batterieladung | BYD/Speicher lädt | immer ≥ 0 |
| Batterieentladung | BYD/Speicher entlädt | immer ≥ 0 |

> **Wichtig**: Bezug und Einspeisung müssen als **separate positive Werte** vorliegen, nicht als ein vorzeichenbehafteter Wert. Fronius, Kostal und andere liefern das manchmal anders — dann braucht es einen Template-Sensor in HA als Zwischenschicht.

### Andere Batterie

Solange Lade- und Entladeleistung als separate nicht-negative Sensoren verfügbar sind, funktioniert das Skript mit jedem Speicher. Nur `SENSOR_BAT_CHARGE` und `SENSOR_BAT_DISCHARGE` anpassen.

### Kein Batteriespeicher

Einfach beide Bat-Sensoren auf einen Sensor setzen der immer 0 zurückgibt (z.B. einen Template-Sensor), oder im Skript `bat_chg_w` und `bat_disch_w` fest auf 0.0 setzen. Die Kernformel vereinfacht sich dann zu `pGrid_send = p_grid_real`.

---

## Dashboard (optional)

Für ein einfaches Lovelace-Dashboard diese Entitäten auf einer Karte zusammenfassen:

```yaml
type: entities
title: Wallbox
entities:
  - entity: sensor.go_echarger_XXXXXX_car_state
    name: Status
  - entity: select.go_echarger_XXXXXX_logic_mode
    name: Lademodus
  - entity: input_select.wallbox_fahrzeug
    name: Fahrzeug
  - entity: input_number.wallbox_zielwert_netz
    name: Zielwert Netz
  - entity: sensor.go_echarger_XXXXXX_power_total
    name: Ladeleistung
  - entity: number.go_echarger_XXXXXX_set_max_ampere_limit
    name: Max. Strom
```

---

## Häufige Fragen

**Der go-e zeigt "Fallback (günstiger Strompreis)" — ist das ein Fehler?**
Nein. Dieser Status bedeutet nur, dass der go-e auf mehr PV-Überschuss wartet. Das ist normales Verhalten bei wenig Sonne.

**Das Skript setzt den Phasenmodus (psm) im Basic-Modus — ist das richtig?**
Nein, das tut es absichtlich nicht. Im Basic-Modus (Default/NextTrip) respektiert das Skript die manuelle Einstellung im go-e.

**Warum lädt das Auto kurz nach dem Anstecken mit maximal 10A?**
Das ist die Ansteck-Sperrzeit (60 Sekunden). In dieser Zeit wird der Ladestrom auf 10A begrenzt damit der go-e und der Wechselrichter Zeit haben sich zu stabilisieren bevor die volle Leistung freigegeben wird.

**Wie füge ich ein zweites Fahrzeug hinzu?**
1. In `FAHRZEUG_PROFILE` im Skript eintragen (Name, mca, schwelle_3p)
2. Denselben Namen in `helpers.yaml` unter `options:` ergänzen
3. HA neu starten

---

## Lizenz

MIT License — frei verwendbar, keine Garantie.

# OSPAL

> **Mirror** - This is a read-only mirror of https://codeberg.org/cyberdream/ospal
> Please submit issues and pull requests there.
> 

### Open Source POCSAG Alert Logger - v0.7.1

OSPAL ist ein headless, konfigurierbares Werkzeug zum Empfangen, Dekodieren und Protokollieren von POCSAG-Nachrichten über einen RTL-SDR-Dongle.
Es ist darauf ausgelegt, auf einem Raspberry Pi, anderen Linux-Einplatinencomputern oder beliebigen Linux-Rechnern mit USB-Anschluss zu laufen - per SSH verwaltet und als systemd-Dienst autonom betrieben, oder direkt in einem Terminal ausgeführt.

---

## Hintergrund

OSPAL wurde teilweise als Alternative zu **PDW** entwickelt - der bekannten Windows-Anwendung für den POCSAG-Empfang, die lange der Standard unter Funkamateuren und Personen war, die Rettungsdienste überwachen.
PDW wurde 2013 offiziell eingestellt, unterstützt keine modernen SMTP-Anforderungen und läuft nicht unter Linux.

Ein Großteil der Inspiration für OSPALs Filterfunktionalität stammt aus PDWs gut durchdachtem und flexiblem Filtersystem.
Obwohl die Entwicklung 2013 endete, verdient PDW alle Anerkennung dafür, den Standard gesetzt zu haben, was ein POCSAG-Werkzeug leisten sollte.
OSPAL ist ein Versuch, dieses Erbe auf einer neuen Plattform und ohne grafische Benutzeroberfläche fortzuführen.

Das Projekt begann mit einem RTL-SDR-Dongle und einem Einplatinencomputer und wurde durch praktische Tests gegen ein echtes Funknetz des schwedischen Rettungsdienstes und Minicalls nationales Pagernetz entwickelt.

---

## Nachrichtenfluss

```
rtl_fm -> multimon-ng
    |
    +-> [raw.log]                     (immer, jede Zeile)
    |
    +-> Terminal (wenn terminal_output = raw)
    |
    +-> parse_pocsag_line()
          |
          +-> (keine POCSAG-Zeile) -> verwerfen
          |
          +-> apply_charset()         (Zeichensatzzuordnung)
                |
                +-> (Adresse/Funktion auf Charset-Blacklist) -> Zuordnung überspringen
                |
                +-> should_blacklist()    [filtering.enabled]
                      |
                      +-> JA (Adresse oder Schlüsselwort auf Blacklist)
                      |       -> verwerfen (nicht in filtered.log, keine Alarme)
                      |
                      +-> NEIN -> [filtered.log]
                                |
                                +-> Terminal (wenn terminal_output = filtered)
                                |
                                +-> find_matching_rule()
                                      |
                                      +-> KEINE ÜBEREINSTIMMUNG -> stop
                                      |
                                      +-> ÜBEREINSTIMMUNG -> [keywords.log]
                                                    |
                                                    +-> Terminal (wenn terminal_output = keywords)
                                                    |
                                                    +-> DuplicateSuppressor
                                                          |
                                                          +-> DUPLIKAT -> stop
                                                          |
                                                          +-> NEU
                                                                +-> Alarm-E-Mail senden
                                                                |   [smtp.log]
                                                                |   (wenn mail_enabled
                                                                |    und mail_alerts)
                                                                |
                                                                +-> ntfy-Benachrichtigung senden
                                                                |   [ntfy.log]
                                                                |   (wenn ntfy_enabled
                                                                |    und ntfy_alerts)
                                                                |
                                                                +-> Alarmskript ausführen
                                                                    (wenn alert.enabled)

error.log       <- Start, Stopp, Neustarts, Ausnahmen (alle Ebenen)
silent_receiver <- warnt per E-Mail/ntfy/Skript, wenn keine Ausgabe von
                   multimon-ng für eine konfigurierbare Anzahl von Minuten
```

---

## Anforderungen

### Hardware
- RTL-SDR-Dongle mit RTL2832U-Chip (R820T/R820T2-Tuner empfohlen, FC0013 funktioniert, hat aber geringere VHF-Empfindlichkeit)
- Einplatinencomputer oder anderer Linux-Rechner mit USB-Anschluss und Netzwerkzugang
- Antenne passend zur verwendeten Frequenz

### Software
- Linux (Debian, Raspberry Pi OS oder Armbian empfohlen)
- Python 3.7 oder neuer
- `rtl-sdr`
- `multimon-ng`

---

## Installation

### 1. Abhängigkeiten installieren

```bash
sudo apt update
sudo apt install -y rtl-sdr multimon-ng python3
```

### 2. Dongle überprüfen

```bash
rtl_test
```

### 3. OSPAL klonen

```bash
git clone https://codeberg.org/cyberdream/ospal.git
cd ospal
```

### 4. ospal.ini konfigurieren

```bash
nano ospal.ini
```

### 5. Steuerskript ausführbar machen

```bash
chmod +x ospal-ctl.sh
```

### 6. Als systemd-Dienst installieren

```bash
sudo ./ospal-ctl.sh install-service
```

### 7. Dongle kalibrieren

```bash
./ospal-ctl.sh calibrate 15
```

Lassen Sie den Dongle vor der Kalibrierung 5-10 Minuten aufwärmen, um beste Ergebnisse zu erzielen.

### 8. E-Mail und/oder ntfy testen

```bash
./ospal-ctl.sh testmail
./ospal-ctl.sh testntfy
```

### 9. OSPAL starten

```bash
./ospal-ctl.sh start
```

---

## Verwendung

```
python3 -u ospal.py              Empfänger starten
python3 -u ospal.py -t [min]     Dongle kalibrieren (PPM, Verstärkung, Abtastrate)
python3 -u ospal.py -m           Test-E-Mail senden
python3 -u ospal.py -n           Test-ntfy-Benachrichtigung senden
python3 -u ospal.py -c file.ini  Angegebene Konfigurationsdatei verwenden
```

Wenn OSPAL als systemd-Dienst läuft, verwenden Sie `ospal-ctl.sh` für Kalibrierung und Testbenachrichtigungen.
Das Skript stoppt den Dienst automatisch, führt den Befehl aus und startet danach neu:

```bash
./ospal-ctl.sh calibrate 15   # Kalibrierung (entspricht -t)
./ospal-ctl.sh testmail       # Test-E-Mail (entspricht -m)
./ospal-ctl.sh testntfy       # Test-ntfy (entspricht -n)
```

---

## Konfiguration

### [receiver]
```ini
frequency = 161.4375M   ; Zu überwachende Frequenz
gain = 19.7             ; Empfängerverstärkung - automatisch durch calibrate gesetzt
ppm = 0                 ; PPM-Versatz - automatisch durch calibrate gesetzt
sample_rate = 22050     ; Abtastrate - automatisch durch calibrate gesetzt
decode_format = alpha   ; alpha (empfohlen), auto, numeric, skyper
```

Das Format `auto` kann doppelte Einträge für dieselbe Nachricht in mehreren Formaten erzeugen,
was dazu führen kann, dass Alarme mehrmals für dasselbe Ereignis ausgelöst werden. `alpha` wird empfohlen.

### [smtp]
```ini
mail_enabled = false    ; Hauptschalter - false deaktiviert alle E-Mails
                        ; Test-E-Mail funktioniert unabhängig von dieser Einstellung immer
mail_alerts = true      ; E-Mail für einzelne Alarme senden
retry_count = 3         ; Anzahl der Versuche bei Fehlern
retry_delay = 30        ; Sekunden zwischen Versuchen
mail_log_time = 06:00   ; Zeit zum Senden täglicher Protokollzusammenfassungen (HH:MM)
mail_log_raw = false
mail_log_filtered = false
mail_log_smtp = false
mail_log_ntfy = false
mail_log_error = false
mail_log_keywords = false

host = smtp.example.com
port = 465              ; 465 für SSL/TLS, 587 für STARTTLS
type = ssl
user = ospal@example.com
password = ihrpasswort  ; Wenn das Passwort %-Zeichen enthält, als %% escapen
recipient = sie@example.com
```

### [ntfy]
```ini
ntfy_enabled = false    ; ntfy-Push-Benachrichtigungen aktivieren
ntfy_alerts = true      ; ntfy-Benachrichtigung für einzelne Alarme senden
url = https://ntfy.sh   ; Oder Ihre selbst gehostete Instanz
topic = ihr-thema
token =                 ; Zugriffstoken für authentifizierte Themen
ntfy_log_raw = false
ntfy_log_filtered = false
ntfy_log_smtp = false
ntfy_log_ntfy = false
ntfy_log_error = false
ntfy_log_keywords = false
```

### [mail_format]
```ini
; Verfügbare Variablen:
;   {keyword} {message} {message_preview} {address} {function}
;   {timestamp} {uptime} {last_restart} {frequency}
;   {errors_exist} {ospal_version} {priority}
subject = {keyword} - {message_preview}
body = {timestamp}
    {message}

    Adresse  : {address}
    Laufzeit : {uptime}
    Fehler   : {errors_exist}
```

### [filtering]
```ini
enabled = false
blacklist_addresses = 1600000
blacklist_keywords = TEST,PROBE
```

### [mail_rules]
```ini
; Regeln sind OR zueinander. AND und NOT (nur Großbuchstaben) sind Operatoren.
; Adressbasierte Regel: ADDRESS:320008
; Kombiniert: brand AND station, alarm NOT test
; ntfy-Priorität pro Regel (min/low/default/high/max):
rule1 = brand
rule1_priority = high
rule2 = unfall
rule2_priority = high
```

### [logging]
```ini
; Relative Pfade werden vom OSPAL-Skriptverzeichnis aufgelöst,
; z.B. logs -> /home/pi/ospal/logs
; Absolute Pfade funktionieren ebenfalls, z.B. /var/log/ospal
log_dir = logs

log_level = info        ; debug, info, warning, error, critical

raw_enabled = true
filtered_enabled = true
keywords_enabled = true
smtp_enabled = true
ntfy_log_enabled = true
error_enabled = true

terminal_output = raw   ; raw, filtered oder keywords

duplicate_suppression = true
duplicate_window_seconds = 120
duplicate_match_chars = 32

archive_keep_days = 0
```

### [charset]
```ini
; Zeichensatzzuordnung für POCSAG (ISO 646-Variante)
; Die Standardwerte gelten für Schwedisch. Passen Sie diese für Ihre Sprache an.
91 = Ä
92 = Ö
93 = Å
123 = ä
124 = ö
125 = å
charset_blacklist_addresses = 1600000
charset_blacklist_functions =
```

### [alert]
```ini
enabled = false
script = alert-scripts/ir_alarm/ir_alarm.py
mode = queue            ; queue oder interrupt
timeout = 600
pass_message = keyword  ; none, keyword oder message
queue_max = 2
```

Im `interrupt`-Modus wird SIGTERM an das laufende Alarmskript gesendet, wenn ein neuer Alarm eintrifft.
Ihr Skript sollte SIGTERM verarbeiten, um vor dem Beenden aufzuräumen:

```python
import signal, sys

def cleanup(sig, frame):
    sys.exit(0)

signal.signal(signal.SIGTERM, cleanup)
```

### [silent_receiver]
```ini
enabled = false
silent_minutes = 12     ; Minuten ohne Ausgabe vor der ersten Warnung
max_warnings = 2        ; Maximale Warnungen pro Stille-Periode
send_mail = true        ; Warnung per E-Mail senden
send_ntfy = false       ; Warnung per ntfy senden
trigger_alert = true    ; Alarmskript mit dem Schlüsselwort OSPAL-SILENT auslösen
```

---

## Protokolldateien

| Datei | Inhalt |
|-------|--------|
| `YYYY-MM-DD-raw.log` | Alle Rohausgaben von multimon-ng |
| `YYYY-MM-DD-filtered.log` | Nachrichten, die den Blacklist-Filter passieren |
| `YYYY-MM-DD-keywords.log` | Nachrichten, die einer Regel entsprachen |
| `YYYY-MM-DD-smtp.log` | SMTP-Ereignisse |
| `YYYY-MM-DD-ntfy.log` | ntfy-Ereignisse |
| `YYYY-MM-DD-error.log` | Fehler, Ausnahmen, Start- und Stopereignisse |

Alle Protokolldateien sind lazy - sie werden nur erstellt, wenn es etwas zu protokollieren gibt.
Um Mitternacht werden die Dateien des Vortages automatisch in `logs/archive/YYYY-MM/` archiviert.

---

## Steuerskript - ospal-ctl.sh

```
./ospal-ctl.sh [Befehl]

  start              OSPAL-Dienst starten
  stop               OSPAL-Dienst stoppen
  restart            Dienst neu starten, z.B. nach Bearbeiten von ospal.ini
  status             Dienststatus und letzte Einträge im gefilterten Protokoll anzeigen
  status-live        Live-Ausgabe via journalctl anzeigen
                     (Strg+C stoppt die Anzeige - OSPAL läuft weiter)
  calibrate [min]    Stoppen, kalibrieren, neu starten. Standard: 15 Minuten
  testmail           Stoppen, Test-E-Mail senden, neu starten
  testntfy           Stoppen, Test-ntfy-Benachrichtigung senden, neu starten
  install-service    OSPAL als systemd-Dienst installieren (erfordert sudo)
```

### install-service

```bash
sudo ./ospal-ctl.sh install-service
```

1. Identifiziert das Verzeichnis, aus dem das Skript ausgeführt wird
2. Identifiziert den Benutzer, der sudo ausgeführt hat - der Dienst läuft als dieser Benutzer, nicht als root
3. Findet die Python-Binärdatei automatisch
4. Erstellt `/etc/systemd/system/ospal.service` mit dem Flag `-u` für ungepufferte Ausgabe
5. Führt `systemctl daemon-reload` aus
6. Aktiviert den Dienst mit `systemctl enable ospal`

Deinstallieren:
```bash
sudo systemctl disable ospal
sudo rm /etc/systemd/system/ospal.service
sudo systemctl daemon-reload
```

---

## Empfehlungen für den Headless-Betrieb

### Ausgabe überwachen

```bash
./ospal-ctl.sh status-live
journalctl -u ospal -n 50
journalctl -u ospal --since "1 hour ago"
```

### WLAN-Energiesparmodus deaktivieren

Auf dem Raspberry Pi ist der WLAN-Energiesparmodus standardmäßig aktiviert. Er kann dazu führen, dass der
Adapter in den Ruhezustand wechselt und nicht korrekt aufwacht, wodurch der Pi per SSH nicht erreichbar ist,
obwohl das System läuft.

Vorübergehend deaktivieren:
```bash
sudo iw dev wlan0 set power_save off
```

Dauerhaft deaktivieren:
```bash
sudo nano /etc/NetworkManager/conf.d/wifi-powersave-off.conf
```
```
[connection]
wifi.powersave = 2
```
```bash
sudo reboot
```

Überprüfen:
```bash
iwconfig wlan0 | grep "Power Management"
```

### Persistentes systemd-Journal aktivieren

Standardmäßig speichert Raspberry Pi OS keine systemd-Protokolle über Neustarts hinweg.
Persistente Protokollierung für bessere Fehlerbehebung aktivieren:

```bash
sudo mkdir -p /var/log/journal
sudo systemd-tmpfiles --create --prefix /var/log/journal
sudo systemctl restart systemd-journald
```

---

## Andere Plattformen

OSPAL wurde unter Linux entwickelt und getestet. Wenn es Ihnen gelingt, OSPAL unter Windows, macOS
oder einer anderen Plattform auszuführen, sind Sie willkommen, Installationsanleitungen per
Pull Request auf Codeberg beizutragen.

---

## Rechtliche Hinweise

**Dies ist keine Rechtsberatung. Überprüfen Sie immer die geltenden Gesetze in Ihrem Land, bevor Sie OSPAL verwenden.**

**Haftungsausschluss:** Der Entwickler übernimmt keine Verantwortung für die Verwendung dieser Software.
Der Benutzer trägt die alleinige Verantwortung dafür, dass die Verwendung von OSPAL in seiner Gerichtsbarkeit rechtmäßig ist.

**Benutzer in den USA:** Die Verwendung von OSPAL in den USA ist aufgrund des Electronic Communications Privacy Act (ECPA) **nicht gestattet**.
Der Entwickler stimmt der Verwendung von OSPAL in den USA oder anderen Gerichtsbarkeiten, in denen eine solche Nutzung rechtswidrig ist, nicht zu.

### Schweden

Der Empfang und die Dekodierung von POCSAG-Signalen ist in Schweden legal. Die relevante Gesetzgebung ist das
**Gesetz über elektronische Kommunikation (2003:389), Kapitel 6, Abschnitt 23**, das die unbefugte Weitergabe
des Inhalts von Funknachrichten, die nicht für Sie bestimmt sind, verbietet.
`mail_enabled` ist aus diesem Grund standardmäßig `false` - verwenden Sie es mit Bedacht.

### Vereinigtes Königreich

Es ist legal, Frequenzen zu scannen, aber illegal, Nachrichteninhalte weiterzugeben.

### USA

Das Dekodieren kommerzieller Pager ist nach dem ECPA illegal. Siehe den Haftungsausschluss oben.

### Andere Länder

In den meisten Ländern ist der Empfang von Pagernachrichten legal, aber die Weitergabe des Inhalts nicht.
Überprüfen Sie immer Ihre lokale Gesetzgebung.

---

## Bekannte Einschränkungen

- Ein einzelner RTL-SDR-Dongle kann nur auf einer Frequenz gleichzeitig hören
- Der FC0013-Tuner hat eine geringere VHF-Empfindlichkeit als R820T/R820T2
- Der PPM-Versatz variiert mit der Dongle-Temperatur - kalibrieren Sie immer mit warmem Dongle
- Passwörter mit `%`-Zeichen müssen in ospal.ini als `%%` escaped werden

---

## Zukünftige Ideen

- Mehrsprachige Unterstützung - gettext mit .po-Dateien (sv, de, es), beim Start automatisch kompiliert
- Konfigurierbares Format für tägliche Protokollzusammenfassungs-E-Mails
- ntfy - tiefere Überprüfung aus Datenschutz- und rechtlicher Perspektive
- Kartenlinks in Alarm-E-Mails - Adresserkennung kombiniert mit einer konfigurierbaren Ortsliste
- Mehrere Frequenzen - Scannen oder Wechseln zwischen Netzwerken
- Anzeigeunterstützung - eingehende Alarme auf einem angeschlossenen Bildschirm anzeigen

---

## Lizenz

OSPAL ist freie Software, lizenziert unter der **GNU General Public License v3.0 (GPL-3.0)**.

Den vollständigen Lizenztext finden Sie in der Datei `LICENSE`.

Der Quellcode ist auf [Codeberg](https://codeberg.org) verfügbar.

---

## Beitragen

Fehlerberichte, Vorschläge und Pull Requests sind auf Codeberg willkommen.

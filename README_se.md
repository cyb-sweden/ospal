# OSPAL

> **Mirror** - Detta är en read-only mirror av https://codeberg.org/cyberdream/ospal
> Skicka gärna issues och pull requests dit.
> 
### Open Source POCSAG Alert Logger - v0.7.1

OSPAL är ett headless, konfigurerbart verktyg för mottagning, avkodning och loggning av POCSAG-meddelanden via en RTL-SDR-dongle.
Det är byggt för att köras på en Raspberry Pi, annan enkortsdator eller vilken Linux-maskin som helst med en USB-port, styras via SSH och sköta sig självt som en systemd-tjänst, eller köras direkt i en terminal.

---

## Bakgrund

OSPAL skapades delvis som ett alternativ till **PDW** - det välkända Windows-programmet för POCSAG-mottagning som länge varit standard bland radioamatörer och blåljusintresserade.
PDW är officiellt färdigutvecklat sedan 2013, saknar stöd för moderna SMTP-krav och körs inte under Linux.

Mycket av inspirationen till OSPAL:s filtreringsfunktioner kommer från PDW:s välgenomtänkta och flexibla filtreringssystem.
Trots att utvecklingen upphörde 2013 förtjänar PDW all heder för att ha satt standarden för vad ett POCSAG-verktyg bör kunna göra.
OSPAL är ett försök att föra arvet vidare på en ny plattform och utan GUI.

Projektet startade med en RTL-SDR-dongle och en enkortsdator, och växte fram genom praktisk testning mot ett verkligt räddningstjänstnät i Sverige samt Minicalls nationella personsökarnät.

---

## Meddelandeflöde

```
rtl_fm -> multimon-ng
    |
    +-> [raw.log]                     (always, every line)
    |
    +-> terminal (if terminal_output = raw)
    |
    +-> parse_pocsag_line()
          |
          +-> (not a POCSAG line) -> discard
          |
          +-> apply_charset()         (character mapping)
                |
                +-> (address/function in charset blacklist) -> skip mapping
                |
                +-> should_blacklist()    [filtering.enabled]
                      |
                      +-> YES (address or keyword blacklisted)
                      |       -> discard (not in filtered.log, no alerts)
                      |
                      +-> NO -> [filtered.log]
                                |
                                +-> terminal (if terminal_output = filtered)
                                |
                                +-> find_matching_rule()
                                      |
                                      +-> NO MATCH -> stop
                                      |
                                      +-> MATCH -> [keywords.log]
                                                    |
                                                    +-> terminal (if terminal_output = keywords)
                                                    |
                                                    +-> DuplicateSuppressor
                                                          |
                                                          +-> DUPLICATE -> stop
                                                          |
                                                          +-> NEW
                                                                +-> send alert mail
                                                                |   [smtp.log]
                                                                |   (if mail_enabled
                                                                |    and mail_alerts)
                                                                |
                                                                +-> send ntfy notification
                                                                |   [ntfy.log]
                                                                |   (if ntfy_enabled
                                                                |    and ntfy_alerts)
                                                                |
                                                                +-> run alert script
                                                                    (if alert.enabled)

error.log      <- startup, shutdown, restarts, exceptions (all levels)
silent_receiver <- varnar via mail/ntfy/alert-script om ingen output
                   från multimon-ng under X minuter
```

---

## Krav

### Hårdvara
- RTL-SDR-dongle med RTL2832U-chip (R820T/R820T2-tuner rekommenderas, FC0013 fungerar men med sämre VHF-känslighet)
- Enkortsdator eller annan Linux-maskin med USB-port och nätverk
- Antenn anpassad för din frekvens

### Mjukvara
- Linux (Debian/Raspberry Pi OS/Armbian rekommenderas)
- Python 3.7 eller senare
- `rtl-sdr`
- `multimon-ng`

---

## Installation

### 1. Installera beroenden

```bash
sudo apt update
sudo apt install -y rtl-sdr multimon-ng python3
```

### 2. Verifiera dongeln

```bash
rtl_test
```

### 3. Klona OSPAL

```bash
git clone https://codeberg.org/cyberdream/ospal.git
cd ospal
```

### 4. Konfigurera ospal.ini

```bash
nano ospal.ini
```

### 5. Gör kontrollscriptet körbart

```bash
chmod +x ospal-ctl.sh
```

### 6. Installera systemd-tjänst

```bash
sudo ./ospal-ctl.sh install-service
```

### 7. Kalibrera dongeln

```bash
./ospal-ctl.sh calibrate 15
```

Låt dongeln värmas upp 5-10 minuter innan kalibrering.

### 8. Testa mail och/eller ntfy

```bash
./ospal-ctl.sh testmail
./ospal-ctl.sh testntfy
```

### 9. Starta

```bash
./ospal-ctl.sh start
```

---

## Användning

```
python3 -u ospal.py              Starta mottagaren
python3 -u ospal.py -t [min]     Kalibrera dongeln (PPM, gain, samplerate)
python3 -u ospal.py -m           Skicka testmail
python3 -u ospal.py -n           Skicka test-ntfy-notis
python3 -u ospal.py -c fil.ini   Använd angiven konfigurationsfil
```

När OSPAL körs som systemd-tjänst används `ospal-ctl.sh` för kalibrering och testutskick.
Scriptet stoppar tjänsten automatiskt, kör kommandot och startar om efteråt:

```bash
./ospal-ctl.sh calibrate 15   # Kalibrering (motsvarar -t)
./ospal-ctl.sh testmail       # Testmail (motsvarar -m)
./ospal-ctl.sh testntfy       # Test-ntfy (motsvarar -n)
```

---

## Konfiguration

### [receiver]
```ini
frequency = 161.4375M   ; Frekvens
gain = 19.7             ; Gain - sätts av calibrate
ppm = 0                 ; PPM - sätts av calibrate
sample_rate = 22050     ; Samplerate - sätts av calibrate
decode_format = alpha   ; alpha (rekommenderas), auto, numeric, skyper
```

### [smtp]
```ini
mail_enabled = false    ; Master-switch - false = inget mail alls
                        ; Testmail fungerar alltid oavsett denna inställning
mail_alerts = true      ; Skicka mail vid enskilda larm
retry_count = 3         ; Antal försök vid misslyckad sändning
retry_delay = 30        ; Sekunder mellan försök
mail_log_time = 06:00   ; Tid för dagliga logg-mail (HH:MM)
mail_log_raw = false
mail_log_filtered = false
mail_log_smtp = false
mail_log_ntfy = false
mail_log_error = false
mail_log_keywords = false

host = smtp.example.com
port = 465              ; 465=SSL/TLS, 587=STARTTLS
type = ssl
user = ospal@example.com
password = lösenord     ; %-tecken i lösenord escapas som %%
recipient = du@example.com
```

### [ntfy]
```ini
ntfy_enabled = false    ; Aktivera ntfy push-notiser
ntfy_alerts = true      ; Skicka ntfy-notis vid enskilda larm
url = https://ntfy.sh   ; Eller din self-hosted instans
topic = ditt-topic
token =                 ; Access-token för autentiserade topics
ntfy_log_raw = false
ntfy_log_filtered = false
ntfy_log_smtp = false
ntfy_log_ntfy = false
ntfy_log_error = false
ntfy_log_keywords = false
```

### [mail_format]
```ini
; Variabler: {keyword} {message} {message_preview} {address} {function}
;            {timestamp} {uptime} {last_restart} {frequency}
;            {errors_exist} {ospal_version} {priority}
subject = {keyword} - {message_preview}
body = {timestamp}
    {message}

    Address  : {address}
    Uptime   : {uptime}
    Errors   : {errors_exist}
```

### [filtering]
```ini
enabled = false
blacklist_addresses = 1600000
blacklist_keywords = PASSNINGSLARM,PROVLARM
```

### [mail_rules]
```ini
; Regler är OR sinsemellan. AND/NOT (VERSALER) är operatorer.
; Adressregel: ADDRESS:320008
; Kombinerat: brand AND viskafors
; ntfy-prioritet per regel (min/low/default/high/max):
rule1 = brand
rule1_priority = high
rule2 = trafikolycka
rule2_priority = high
```

### [logging]
```ini
; Relativ sökväg utgår från OSPAL-mappen, t.ex. logs -> /home/dk/OSPAL/logs
; Absolut sökväg fungerar också, t.ex. /var/log/ospal
log_dir = logs

log_level = info        ; debug, info, warning, error, critical

raw_enabled = true
filtered_enabled = true
keywords_enabled = true
smtp_enabled = true
ntfy_log_enabled = true
error_enabled = true

terminal_output = raw   ; raw, filtered eller keywords

duplicate_suppression = true
duplicate_window_seconds = 120
duplicate_match_chars = 32

archive_keep_days = 0
```

### [charset]
```ini
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
mode = queue            ; queue eller interrupt
timeout = 600
pass_message = keyword  ; none, keyword eller message
queue_max = 2
```

I `interrupt`-läge skickas SIGTERM till det körande alert-scriptet vid nytt larm.
Ditt script bör fånga SIGTERM och städa upp innan det avslutas:

```python
import signal, sys

def cleanup(sig, frame):
    sys.exit(0)

signal.signal(signal.SIGTERM, cleanup)
```

### [silent_receiver]
```ini
enabled = false
silent_minutes = 12     ; Minuter utan output innan varning skickas
max_warnings = 2        ; Max antal varningar per tystnadperiod
send_mail = true        ; Skicka varning via mail
send_ntfy = false       ; Skicka varning via ntfy
trigger_alert = true    ; Trigga alert-script med OSPAL-SILENT
```

---

## Loggfiler

| Fil | Innehåll |
|-----|----------|
| `YYYY-MM-DD-raw.log` | All rådata från multimon-ng |
| `YYYY-MM-DD-filtered.log` | Meddelanden som passerar blacklist-filtret |
| `YYYY-MM-DD-keywords.log` | Meddelanden som matchade en regel |
| `YYYY-MM-DD-smtp.log` | SMTP-händelser |
| `YYYY-MM-DD-ntfy.log` | ntfy-händelser |
| `YYYY-MM-DD-error.log` | Fel, undantag, start/stopp-händelser |

Alla loggfiler är lazy - de skapas bara om det finns något att logga. Vid midnatt arkiveras föregående dygns filer automatiskt till `logs/archive/YYYY-MM/`.

---

## Kontrollscript - ospal-ctl.sh

```
./ospal-ctl.sh [kommando]

  start              Starta tjänsten
  stop               Stoppa tjänsten
  restart            Starta om (efter redigering av ospal.ini)
  status             Visa status + senaste filtered-loggen
  status-live        Visa live output via journalctl
                     (Ctrl+C avslutar visningen - OSPAL kör vidare)
  calibrate [min]    Stoppa, kalibrera, starta om. Standard: 15 min
  testmail           Stoppa, skicka testmail, starta om
  testntfy           Stoppa, skicka test-ntfy-notis, starta om
  install-service    Installera systemd-tjänst (kräver sudo)
```

### install-service

```bash
sudo ./ospal-ctl.sh install-service
```

1. Identifierar mappen scriptet körs från
2. Identifierar användaren som körde sudo (tjänsten körs som denne, inte root)
3. Hittar Python-binären automatiskt
4. Skapar `/etc/systemd/system/ospal.service` med `-u` för unbuffrad output
5. Kör `systemctl daemon-reload`
6. Aktiverar tjänsten med `systemctl enable ospal`

Avinstallera:
```bash
sudo systemctl disable ospal
sudo rm /etc/systemd/system/ospal.service
sudo systemctl daemon-reload
```

---

## Rekommendationer vid headless drift

### Visa output

```bash
./ospal-ctl.sh status-live
journalctl -u ospal -n 50
journalctl -u ospal --since "1 hour ago"
```

### Stäng av WiFi-strömspararläget

På Raspberry Pi är WiFi-strömspararläget aktiverat som standard. Det kan göra att adaptern somnar och inte vaknar korrekt, vilket gör RPi:n onåbar via SSH trots att systemet kör.

Stäng av tillfälligt:
```bash
sudo iw dev wlan0 set power_save off
```

Gör det permanent:
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

Verifiera:
```bash
iwconfig wlan0 | grep "Power Management"
```

### Aktivera persistent systemd-journal

```bash
sudo mkdir -p /var/log/journal
sudo systemd-tmpfiles --create --prefix /var/log/journal
sudo systemctl restart systemd-journald
```

---

## Windows och andra plattformar

OSPAL är utvecklat och testat på Linux. Om du lyckas köra OSPAL på Windows, macOS eller andra plattformar är du välkommen att bidra med instruktioner via ett pull request på Codeberg.

---

## Juridisk information

**Detta är inte juridisk rådgivning. Kontrollera alltid gällande lagstiftning.**

**Ansvarsfriskrivning:** Utvecklaren tar inget ansvar för hur mjukvaran används. Användaren bär ensamt ansvar för laglig användning.

**Användare i USA:** Användning av OSPAL i USA är **inte tillåten** på grund av Electronic Communications Privacy Act (ECPA). Utvecklaren medger inte användning i USA eller andra jurisdiktioner där sådan användning strider mot lag.

### Sverige

Att ta emot POCSAG-signaler är lagligt. **Lag om elektronisk kommunikation (2003:389), 6 kap 23 paragraf** förbjuder att föra vidare meddelandeinnehåll som inte är avsett för dig. `mail_enabled` är false som standard av detta skäl - använd med omdöme.

### Storbritannien

Lagligt att scanna, olagligt att avslöja innehåll.

### USA

Olagligt enligt ECPA. Se ovan.

### Övriga länder

Kontrollera lokal lagstiftning. I de flesta länder är mottagning laglig men spridning olaglig.

---

## Kända begränsningar

- En dongle kan bara lyssna på en frekvens åt gången
- FC0013 har sämre VHF-känslighet än R820T/R820T2
- PPM varierar med temperatur - kalibrera med varm dongle
- `%` i lösenord måste escapas som `%%` i ini-filen

---

## Framtida idéer

- **Flerspråkighet** - gettext med .po-filer (sv, de, es), auto-kompilering vid start
- **Konfigurerbart format för loggmail** - samma variabelsystem som för larmmail
- **ntfy** - djupdykning ur integritets/juridikperspektiv
- **Google Maps-länkar** - adressparsning + ortslista i mailinnehåll
- **Flera frekvenser** - scanning/växling mellan RTJ-nät och Minicall
- **NVDB-integration** - Lantmäteriets vägdatabas för adressparsning
- **Display-stöd** - visa larm på ansluten skärm

---

## Licens

OSPAL är fri mjukvara licensierad under **GNU General Public License v3.0 (GPL-3.0)**.

Se filen `LICENSE` för fullständig licenstext.

Källkod finns på [Codeberg](https://codeberg.org).

---

## Bidra

Buggrapporter, förbättringsförslag och pull requests är välkomna på Codeberg.

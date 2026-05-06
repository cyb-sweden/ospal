# OSPAL

> **Mirror** - This is a read-only mirror of https://codeberg.org/cyberdream/ospal
> Please submit issues and pull requests there.
> 
### Open Source POCSAG Alert Logger - v0.7.1

OSPAL is a headless, configurable tool for receiving, decoding and logging POCSAG messages via an RTL-SDR dongle.
It is designed to run on a Raspberry Pi, other Linux single-board computers, or any Linux machine with a USB port - managed over SSH and operating autonomously as a systemd service, or run directly in a terminal.

---

## Background

OSPAL was created partly as an alternative to **PDW** - the well-known Windows application for POCSAG reception that has long been the standard among radio enthusiasts and those monitoring emergency services.
PDW has been officially discontinued since 2013, lacks support for modern SMTP requirements and does not run on Linux.

Much of the inspiration for OSPAL's filtering functionality comes from PDW's well-designed and flexible filtering system.
Despite development ending in 2013, PDW deserves full credit for setting the standard for what a POCSAG tool should be capable of.
OSPAL is an attempt to carry that legacy forward on a new platform and without a graphical interface.

The project started with an RTL-SDR dongle and a single-board computer, and developed through practical testing against a real emergency services pager network in Sweden and Minicall's national paging network.

---

## Message flow

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

error.log       <- startup, shutdown, restarts, exceptions (all levels)
silent_receiver <- warns via mail/ntfy/alert script if no output from
                   multimon-ng for a configurable number of minutes
```

---

## Requirements

### Hardware
- RTL-SDR dongle with RTL2832U chip (R820T/R820T2 tuner recommended, FC0013 works but with reduced VHF sensitivity)
- Single-board computer or other Linux machine with a USB port and network access
- Antenna suited to your frequency

### Software
- Linux (Debian, Raspberry Pi OS or Armbian recommended)
- Python 3.7 or later
- `rtl-sdr`
- `multimon-ng`

---

## Installation

### 1. Install dependencies

```bash
sudo apt update
sudo apt install -y rtl-sdr multimon-ng python3
```

### 2. Verify the dongle

```bash
rtl_test
```

### 3. Clone OSPAL

```bash
git clone https://codeberg.org/cyberdream/ospal.git
cd ospal
```

### 4. Configure ospal.ini

```bash
cp ospal.ini.example ospal.ini
nano ospal.ini
```

### 5. Make the control script executable

```bash
chmod +x ospal-ctl.sh
```

### 6. Install as a systemd service (skip this step if you only want to run ospal in terminal)

```bash
sudo ./ospal-ctl.sh install-service
```

### 7. Calibrate the dongle

```bash
./ospal-ctl.sh calibrate 15
```

Let the dongle warm up for 5-10 minutes before calibrating for best results.
If calibration return numbers that are all over the place, let the dongle warm up for longer,
or just try to set ppm = 0. 

### 8. Test mail and/or ntfy

```bash
./ospal-ctl.sh testmail
./ospal-ctl.sh testntfy
```

### 9. Start OSPAL

```bash
./ospal-ctl.sh start
```

---

## Usage

```
python3 -u ospal.py              Start the receiver
python3 -u ospal.py -t [min]     Calibrate dongle (PPM, gain, sample rate)
python3 -u ospal.py -m           Send test mail
python3 -u ospal.py -n           Send test ntfy notification
python3 -u ospal.py -c file.ini  Use specified config file
```

When OSPAL runs as a systemd service, use `ospal-ctl.sh` for calibration and test notifications.
The script stops the service automatically, runs the command, and restarts afterwards:

```bash
./ospal-ctl.sh calibrate 15   # Calibration (equivalent to -t)
./ospal-ctl.sh testmail       # Test mail (equivalent to -m)
./ospal-ctl.sh testntfy       # Test ntfy (equivalent to -n)
```

---

## Configuration

### [receiver]
```ini
frequency = 161.4375M   ; Frequency to listen on
gain = 19.7             ; Receiver gain - set automatically by calibrate
ppm = 0                 ; PPM offset - set automatically by calibrate
sample_rate = 22050     ; Sample rate - set automatically by calibrate
decode_format = alpha   ; alpha (recommended), auto, numeric, skyper
```

The `auto` format may produce duplicate entries for the same message in multiple formats,
potentially triggering alerts more than once for the same event. `alpha` is recommended.

### [smtp]
```ini
mail_enabled = false    ; Master switch - false disables all mail
                        ; Test mail always works regardless of this setting
mail_alerts = true      ; Send mail for individual alerts
retry_count = 3         ; Number of attempts on failure
retry_delay = 30        ; Seconds between attempts
mail_log_time = 06:00   ; Time to send daily log summaries (HH:MM)
mail_log_raw = false
mail_log_filtered = false
mail_log_smtp = false
mail_log_ntfy = false
mail_log_error = false
mail_log_keywords = false

host = smtp.example.com
port = 465              ; 465 for SSL/TLS, 587 for STARTTLS
type = ssl
user = ospal@example.com
password = yourpassword ; If password contains % characters, escape them as %%
recipient = you@example.com
```

### [ntfy]
```ini
ntfy_enabled = false    ; Enable ntfy push notifications
ntfy_alerts = true      ; Send ntfy notification for individual alerts
url = https://ntfy.sh   ; Or your self-hosted instance
topic = your-topic
token =                 ; Access token for authenticated topics
ntfy_log_raw = false
ntfy_log_filtered = false
ntfy_log_smtp = false
ntfy_log_ntfy = false
ntfy_log_error = false
ntfy_log_keywords = false
```

### [mail_format]
```ini
; Available variables:
;   {keyword} {message} {message_preview} {address} {function}
;   {timestamp} {uptime} {last_restart} {frequency}
;   {errors_exist} {ospal_version} {priority}
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
blacklist_keywords = TEST,DRILL
```

### [mail_rules]
```ini
; Rules are OR between each other. AND and NOT (uppercase only) are operators.
; Address-based rule: ADDRESS:320008
; Combined: fire AND station, alarm NOT test
; ntfy priority per rule (min/low/default/high/max):
rule1 = fire
rule1_priority = high
rule2 = accident
rule2_priority = high
```

### [logging]
```ini
; Relative paths are resolved from the OSPAL script directory,
; e.g. logs -> /home/pi/ospal/logs
; Absolute paths also work, e.g. /var/log/ospal
log_dir = logs

log_level = info        ; debug, info, warning, error, critical

raw_enabled = true
filtered_enabled = true
keywords_enabled = true
smtp_enabled = true
ntfy_log_enabled = true
error_enabled = true

terminal_output = raw   ; raw, filtered or keywords

duplicate_suppression = true
duplicate_window_seconds = 120
duplicate_match_chars = 32

archive_keep_days = 0
```

### [charset]
```ini
; Character mapping for POCSAG (ISO 646 variant)
; The default values below are for Swedish. Adjust for your language if needed.
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
mode = queue            ; queue or interrupt
timeout = 600
pass_message = keyword  ; none, keyword or message
queue_max = 2
```

In `interrupt` mode, SIGTERM is sent to the running alert script when a new alert arrives.
Your script should handle SIGTERM to clean up before exiting:

```python
import signal, sys

def cleanup(sig, frame):
    sys.exit(0)

signal.signal(signal.SIGTERM, cleanup)
```

### [silent_receiver]
```ini
enabled = false
silent_minutes = 12     ; Minutes without output before first warning
max_warnings = 2        ; Maximum warnings per silence period
send_mail = true        ; Send warning via mail
send_ntfy = false       ; Send warning via ntfy
trigger_alert = true    ; Trigger alert script with keyword OSPAL-SILENT
```

---

## Log files

| File | Contents |
|------|----------|
| `YYYY-MM-DD-raw.log` | All raw output from multimon-ng |
| `YYYY-MM-DD-filtered.log` | Messages passing the blacklist filter |
| `YYYY-MM-DD-keywords.log` | Messages that matched a rule |
| `YYYY-MM-DD-smtp.log` | SMTP events |
| `YYYY-MM-DD-ntfy.log` | ntfy events |
| `YYYY-MM-DD-error.log` | Errors, exceptions, start and stop events |

All log files are lazy - they are only created when there is something to log.
At midnight, the previous day's files are automatically archived to `logs/archive/YYYY-MM/`.

---

## Control script - ospal-ctl.sh

```
./ospal-ctl.sh [command]

  start              Start the OSPAL service
  stop               Stop the OSPAL service
  restart            Restart the service, e.g. after editing ospal.ini
  status             Show service status and last entries in today's filtered log
  status-live        Show live output via journalctl
                     (Ctrl+C stops viewing - OSPAL keeps running)
  calibrate [min]    Stop, calibrate, restart. Default: 15 minutes
  testmail           Stop, send test mail, restart
  testntfy           Stop, send test ntfy notification, restart
  install-service    Install OSPAL as a systemd service (requires sudo)
```

### install-service

```bash
sudo ./ospal-ctl.sh install-service
```

1. Identifies the directory the script is run from
2. Identifies the user who ran sudo - the service runs as this user, not root
3. Locates the Python binary automatically
4. Creates `/etc/systemd/system/ospal.service` with the `-u` flag for unbuffered output
5. Runs `systemctl daemon-reload`
6. Enables the service with `systemctl enable ospal`

To uninstall:
```bash
sudo systemctl disable ospal
sudo rm /etc/systemd/system/ospal.service
sudo systemctl daemon-reload
```

---

## Recommendations for headless operation

### Monitoring output

```bash
./ospal-ctl.sh status-live
journalctl -u ospal -n 50
journalctl -u ospal --since "1 hour ago"
```

### Disable WiFi power saving

On Raspberry Pi, WiFi power saving is enabled by default. It can cause the adapter
to sleep and fail to wake correctly, making the Pi unreachable over SSH even though
the system is otherwise running.

Disable temporarily:
```bash
sudo iw dev wlan0 set power_save off
```

Make it permanent:
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

Verify:
```bash
iwconfig wlan0 | grep "Power Management"
```

### Enable persistent systemd journal

By default, Raspberry Pi OS does not persist systemd logs across reboots.
Enable persistent logging for better troubleshooting:

```bash
sudo mkdir -p /var/log/journal
sudo systemd-tmpfiles --create --prefix /var/log/journal
sudo systemctl restart systemd-journald
```

After this, logs survive reboots and you can use `journalctl -b -1` to inspect
logs from the previous session.

---

## Other platforms

OSPAL is developed and tested on Linux. If you manage to run OSPAL on Windows, macOS
or any other platform, you are welcome to contribute installation instructions via
a pull request on Codeberg.

---

## Legal information

**This is not legal advice. Always check the applicable laws in your country before using OSPAL.**

**Disclaimer:** The developer takes no responsibility for how this software is used.
The user bears sole responsibility for ensuring that use of OSPAL is lawful in their jurisdiction.

**Users in the USA:** Use of OSPAL in the USA is **not permitted** due to the Electronic
Communications Privacy Act (ECPA). The developer does not consent to use of OSPAL in the USA
or any other jurisdiction where such use is unlawful.

### Sweden

Receiving and decoding POCSAG signals is legal in Sweden. The relevant legislation is
**Electronic Communications Act (2003:389), Chapter 6, Section 23**, which prohibits
unauthorised disclosure of the contents of radio messages not intended for you.
`mail_enabled` defaults to `false` for this reason - use with judgement.

### United Kingdom

It is legal to scan frequencies, but illegal to disclose message content.

### USA

Decoding commercial pagers is illegal under the ECPA. See the disclaimer above.

### Other countries

In most countries, receiving pager messages is legal but distributing the content is not.
Always check your local legislation.

---

## Known limitations

- A single RTL-SDR dongle can only listen on one frequency at a time
- The FC0013 tuner has lower VHF sensitivity than R820T/R820T2
- PPM offset varies with dongle temperature - always calibrate with a warm dongle
- Passwords containing `%` characters must be escaped as `%%` in ospal.ini

---

## Future ideas

- Multilingual support - gettext with .po files (sv, de, es), compiled automatically at startup
- Configurable format for daily log summary mails
- ntfy - deeper review from a privacy and legal perspective
- Map links in alert mails - address parsing combined with a configurable place name list
- Multiple frequencies - scanning or switching between networks
- Display support - show incoming alerts on a connected screen

---

## Licence

OSPAL is free software licenced under the **GNU General Public License v3.0 (GPL-3.0)**.

See the `LICENSE` file for the full licence text.

Source code is available on [Codeberg](https://codeberg.org).

---

## Contributing

Bug reports, suggestions and pull requests are welcome on Codeberg.

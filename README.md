# OSPAL

OSPAL - Open Source POCSAG Alert Logger
A headless, configurable POCSAG receiver for Raspberry Pi, other Linux single-board computers, or any Linux machine with a USB port. Receives pager messages via an RTL-SDR dongle, decodes them with multimon-ng, logs to daily files and sends alerts via SMTP and/or ntfy. Runs unattended as a systemd service or directly in a terminal.
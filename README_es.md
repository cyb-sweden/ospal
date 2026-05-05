# OSPAL
### Open Source POCSAG Alert Logger - v0.7.1

OSPAL es una herramienta headless y configurable para recibir, decodificar y registrar mensajes POCSAG a través de un dongle RTL-SDR.
Está diseñada para ejecutarse en una Raspberry Pi, otras computadoras de placa única con Linux, o cualquier máquina Linux con un puerto USB - gestionada por SSH y funcionando de forma autónoma como un servicio systemd, o ejecutada directamente en una terminal.

---

## Antecedentes

OSPAL fue creado en parte como una alternativa a **PDW** - la conocida aplicación de Windows para la recepción POCSAG que ha sido el estándar entre los aficionados a la radio y quienes monitorean los servicios de emergencia.
PDW fue oficialmente descontinuado en 2013, carece de soporte para los requisitos modernos de SMTP y no funciona en Linux.

Gran parte de la inspiración para la funcionalidad de filtrado de OSPAL proviene del sistema de filtrado bien diseñado y flexible de PDW.
A pesar de que el desarrollo terminó en 2013, PDW merece todo el crédito por establecer el estándar de lo que debería ser capaz una herramienta POCSAG.
OSPAL es un intento de llevar ese legado hacia adelante en una nueva plataforma y sin interfaz gráfica.

El proyecto comenzó con un dongle RTL-SDR y una computadora de placa única, y se desarrolló mediante pruebas prácticas contra una red de buscapersonas de servicios de emergencia real en Suecia y la red nacional de buscapersonas de Minicall.

---

## Flujo de mensajes

```
rtl_fm -> multimon-ng
    |
    +-> [raw.log]                     (siempre, cada línea)
    |
    +-> terminal (si terminal_output = raw)
    |
    +-> parse_pocsag_line()
          |
          +-> (no es una línea POCSAG) -> descartar
          |
          +-> apply_charset()         (mapeo de caracteres)
                |
                +-> (dirección/función en lista negra charset) -> omitir mapeo
                |
                +-> should_blacklist()    [filtering.enabled]
                      |
                      +-> SI (dirección o palabra clave en lista negra)
                      |       -> descartar (no en filtered.log, sin alertas)
                      |
                      +-> NO -> [filtered.log]
                                |
                                +-> terminal (si terminal_output = filtered)
                                |
                                +-> find_matching_rule()
                                      |
                                      +-> SIN COINCIDENCIA -> detener
                                      |
                                      +-> COINCIDENCIA -> [keywords.log]
                                                    |
                                                    +-> terminal (si terminal_output = keywords)
                                                    |
                                                    +-> DuplicateSuppressor
                                                          |
                                                          +-> DUPLICADO -> detener
                                                          |
                                                          +-> NUEVO
                                                                +-> enviar correo de alerta
                                                                |   [smtp.log]
                                                                |   (si mail_enabled
                                                                |    y mail_alerts)
                                                                |
                                                                +-> enviar notificación ntfy
                                                                |   [ntfy.log]
                                                                |   (si ntfy_enabled
                                                                |    y ntfy_alerts)
                                                                |
                                                                +-> ejecutar script de alerta
                                                                    (si alert.enabled)

error.log       <- inicio, apagado, reinicios, excepciones (todos los niveles)
silent_receiver <- avisa por correo/ntfy/script si no hay salida de
                   multimon-ng durante un número configurable de minutos
```

---

## Requisitos

### Hardware
- Dongle RTL-SDR con chip RTL2832U (se recomienda sintonizador R820T/R820T2, FC0013 funciona pero con sensibilidad VHF reducida)
- Computadora de placa única u otra máquina Linux con un puerto USB y acceso a red
- Antena adecuada para su frecuencia

### Software
- Linux (se recomienda Debian, Raspberry Pi OS o Armbian)
- Python 3.7 o posterior
- `rtl-sdr`
- `multimon-ng`

---

## Instalación

### 1. Instalar dependencias

```bash
sudo apt update
sudo apt install -y rtl-sdr multimon-ng python3
```

### 2. Verificar el dongle

```bash
rtl_test
```

### 3. Clonar OSPAL

```bash
git clone https://codeberg.org/cyberdream/ospal.git
cd ospal
```

### 4. Configurar ospal.ini

```bash
nano ospal.ini
```

### 5. Hacer ejecutable el script de control

```bash
chmod +x ospal-ctl.sh
```

### 6. Instalar como servicio systemd

```bash
sudo ./ospal-ctl.sh install-service
```

### 7. Calibrar el dongle

```bash
./ospal-ctl.sh calibrate 15
```

Deje que el dongle se caliente durante 5-10 minutos antes de calibrar para obtener mejores resultados.

### 8. Probar correo y/o ntfy

```bash
./ospal-ctl.sh testmail
./ospal-ctl.sh testntfy
```

### 9. Iniciar OSPAL

```bash
./ospal-ctl.sh start
```

---

## Uso

```
python3 -u ospal.py              Iniciar el receptor
python3 -u ospal.py -t [min]     Calibrar dongle (PPM, ganancia, tasa de muestreo)
python3 -u ospal.py -m           Enviar correo de prueba
python3 -u ospal.py -n           Enviar notificación ntfy de prueba
python3 -u ospal.py -c file.ini  Usar archivo de configuración especificado
```

Cuando OSPAL se ejecuta como servicio systemd, use `ospal-ctl.sh` para calibración y notificaciones de prueba.
El script detiene el servicio automáticamente, ejecuta el comando y reinicia después:

```bash
./ospal-ctl.sh calibrate 15   # Calibración (equivalente a -t)
./ospal-ctl.sh testmail       # Correo de prueba (equivalente a -m)
./ospal-ctl.sh testntfy       # Prueba ntfy (equivalente a -n)
```

---

## Configuración

### [receiver]
```ini
frequency = 161.4375M   ; Frecuencia de escucha
gain = 19.7             ; Ganancia del receptor - establecida automáticamente por calibrate
ppm = 0                 ; Offset PPM - establecido automáticamente por calibrate
sample_rate = 22050     ; Tasa de muestreo - establecida automáticamente por calibrate
decode_format = alpha   ; alpha (recomendado), auto, numeric, skyper
```

El formato `auto` puede producir entradas duplicadas del mismo mensaje en múltiples formatos,
lo que podría activar alertas más de una vez para el mismo evento. Se recomienda `alpha`.

### [smtp]
```ini
mail_enabled = false    ; Interruptor maestro - false deshabilita todo el correo
                        ; El correo de prueba siempre funciona independientemente de esta configuración
mail_alerts = true      ; Enviar correo para alertas individuales
retry_count = 3         ; Número de intentos en caso de fallo
retry_delay = 30        ; Segundos entre intentos
mail_log_time = 06:00   ; Hora para enviar resúmenes diarios de registros (HH:MM)
mail_log_raw = false
mail_log_filtered = false
mail_log_smtp = false
mail_log_ntfy = false
mail_log_error = false
mail_log_keywords = false

host = smtp.example.com
port = 465              ; 465 para SSL/TLS, 587 para STARTTLS
type = ssl
user = ospal@example.com
password = sucontraseña ; Si la contraseña contiene caracteres %, escápelos como %%
recipient = usted@example.com
```

### [ntfy]
```ini
ntfy_enabled = false    ; Activar notificaciones push ntfy
ntfy_alerts = true      ; Enviar notificación ntfy para alertas individuales
url = https://ntfy.sh   ; O su instancia auto-alojada
topic = su-tema
token =                 ; Token de acceso para temas autenticados
ntfy_log_raw = false
ntfy_log_filtered = false
ntfy_log_smtp = false
ntfy_log_ntfy = false
ntfy_log_error = false
ntfy_log_keywords = false
```

### [mail_format]
```ini
; Variables disponibles:
;   {keyword} {message} {message_preview} {address} {function}
;   {timestamp} {uptime} {last_restart} {frequency}
;   {errors_exist} {ospal_version} {priority}
subject = {keyword} - {message_preview}
body = {timestamp}
    {message}

    Direccion: {address}
    Tiempo    : {uptime}
    Errores   : {errors_exist}
```

### [filtering]
```ini
enabled = false
blacklist_addresses = 1600000
blacklist_keywords = TEST,PRUEBA
```

### [mail_rules]
```ini
; Las reglas son OR entre sí. AND y NOT (solo mayúsculas) son operadores.
; Regla basada en dirección: ADDRESS:320008
; Combinada: incendio AND estacion, alarma NOT prueba
; Prioridad ntfy por regla (min/low/default/high/max):
rule1 = incendio
rule1_priority = high
rule2 = accidente
rule2_priority = high
```

### [logging]
```ini
; Las rutas relativas se resuelven desde el directorio del script OSPAL,
; p.ej. logs -> /home/pi/ospal/logs
; Las rutas absolutas también funcionan, p.ej. /var/log/ospal
log_dir = logs

log_level = info        ; debug, info, warning, error, critical

raw_enabled = true
filtered_enabled = true
keywords_enabled = true
smtp_enabled = true
ntfy_log_enabled = true
error_enabled = true

terminal_output = raw   ; raw, filtered o keywords

duplicate_suppression = true
duplicate_window_seconds = 120
duplicate_match_chars = 32

archive_keep_days = 0
```

### [charset]
```ini
; Mapeo de caracteres para POCSAG (variante ISO 646)
; Los valores predeterminados son para sueco. Ajuste según su idioma si es necesario.
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
mode = queue            ; queue o interrupt
timeout = 600
pass_message = keyword  ; none, keyword o message
queue_max = 2
```

En modo `interrupt`, se envía SIGTERM al script de alerta en ejecución cuando llega una nueva alerta.
Su script debe manejar SIGTERM para limpiar antes de salir:

```python
import signal, sys

def cleanup(sig, frame):
    sys.exit(0)

signal.signal(signal.SIGTERM, cleanup)
```

### [silent_receiver]
```ini
enabled = false
silent_minutes = 12     ; Minutos sin salida antes de la primera advertencia
max_warnings = 2        ; Máximo de advertencias por período de silencio
send_mail = true        ; Enviar advertencia por correo
send_ntfy = false       ; Enviar advertencia por ntfy
trigger_alert = true    ; Activar script de alerta con la palabra clave OSPAL-SILENT
```

---

## Archivos de registro

| Archivo | Contenido |
|---------|-----------|
| `YYYY-MM-DD-raw.log` | Toda la salida bruta de multimon-ng |
| `YYYY-MM-DD-filtered.log` | Mensajes que pasan el filtro de lista negra |
| `YYYY-MM-DD-keywords.log` | Mensajes que coincidieron con una regla |
| `YYYY-MM-DD-smtp.log` | Eventos SMTP |
| `YYYY-MM-DD-ntfy.log` | Eventos ntfy |
| `YYYY-MM-DD-error.log` | Errores, excepciones, eventos de inicio y parada |

Todos los archivos de registro son lazy - solo se crean cuando hay algo que registrar.
A medianoche, los archivos del día anterior se archivan automáticamente en `logs/archive/YYYY-MM/`.

---

## Script de control - ospal-ctl.sh

```
./ospal-ctl.sh [comando]

  start              Iniciar el servicio OSPAL
  stop               Detener el servicio OSPAL
  restart            Reiniciar el servicio, p.ej. después de editar ospal.ini
  status             Mostrar estado del servicio y últimas entradas del registro filtrado
  status-live        Mostrar salida en vivo via journalctl
                     (Ctrl+C detiene la visualización - OSPAL sigue ejecutándose)
  calibrate [min]    Detener, calibrar, reiniciar. Predeterminado: 15 minutos
  testmail           Detener, enviar correo de prueba, reiniciar
  testntfy           Detener, enviar notificación ntfy de prueba, reiniciar
  install-service    Instalar OSPAL como servicio systemd (requiere sudo)
```

### install-service

```bash
sudo ./ospal-ctl.sh install-service
```

1. Identifica el directorio desde el que se ejecuta el script
2. Identifica el usuario que ejecutó sudo - el servicio se ejecuta como este usuario, no como root
3. Localiza el binario de Python automáticamente
4. Crea `/etc/systemd/system/ospal.service` con la bandera `-u` para salida sin buffer
5. Ejecuta `systemctl daemon-reload`
6. Activa el servicio con `systemctl enable ospal`

Para desinstalar:
```bash
sudo systemctl disable ospal
sudo rm /etc/systemd/system/ospal.service
sudo systemctl daemon-reload
```

---

## Recomendaciones para operación headless

### Monitoreo de salida

```bash
./ospal-ctl.sh status-live
journalctl -u ospal -n 50
journalctl -u ospal --since "1 hour ago"
```

### Deshabilitar el ahorro de energía WiFi

En Raspberry Pi, el ahorro de energía WiFi está habilitado de forma predeterminada. Puede hacer que el adaptador
entre en suspensión y no despierte correctamente, haciendo que la Pi sea inaccesible por SSH aunque
el sistema esté funcionando.

Deshabilitar temporalmente:
```bash
sudo iw dev wlan0 set power_save off
```

Hacerlo permanente:
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

Verificar:
```bash
iwconfig wlan0 | grep "Power Management"
```

### Habilitar el diario systemd persistente

Por defecto, Raspberry Pi OS no persiste los registros systemd entre reinicios.
Habilitar el registro persistente para mejor resolución de problemas:

```bash
sudo mkdir -p /var/log/journal
sudo systemd-tmpfiles --create --prefix /var/log/journal
sudo systemctl restart systemd-journald
```

---

## Otras plataformas

OSPAL está desarrollado y probado en Linux. Si logra ejecutar OSPAL en Windows, macOS
u otra plataforma, es bienvenido a contribuir con instrucciones de instalación mediante
un pull request en Codeberg.

---

## Información legal

**Esto no es asesoramiento legal. Siempre verifique las leyes aplicables en su país antes de usar OSPAL.**

**Descargo de responsabilidad:** El desarrollador no asume ninguna responsabilidad por cómo se usa este software.
El usuario asume la responsabilidad exclusiva de garantizar que el uso de OSPAL sea legal en su jurisdicción.

**Usuarios en EE.UU.:** El uso de OSPAL en EE.UU. **no está permitido** debido a la Ley de Privacidad de Comunicaciones Electrónicas (ECPA).
El desarrollador no consiente el uso de OSPAL en EE.UU. ni en ninguna otra jurisdicción donde dicho uso sea ilegal.

### Suecia

Recibir y decodificar señales POCSAG es legal en Suecia. La legislación relevante es la
**Ley de Comunicaciones Electrónicas (2003:389), Capítulo 6, Sección 23**, que prohíbe
la divulgación no autorizada del contenido de mensajes de radio no destinados a usted.
`mail_enabled` tiene como valor predeterminado `false` por esta razón - use con criterio.

### Reino Unido

Es legal escanear frecuencias, pero ilegal divulgar el contenido de los mensajes.

### EE.UU.

Decodificar buscapersonas comerciales es ilegal según la ECPA. Vea el descargo de responsabilidad anterior.

### Otros países

En la mayoría de los países, recibir mensajes de buscapersonas es legal pero distribuir el contenido no lo es.
Consulte siempre su legislación local.

---

## Limitaciones conocidas

- Un solo dongle RTL-SDR solo puede escuchar en una frecuencia a la vez
- El sintonizador FC0013 tiene menor sensibilidad VHF que el R820T/R820T2
- El offset PPM varía con la temperatura del dongle - calibre siempre con el dongle caliente
- Las contraseñas que contienen caracteres `%` deben escaparse como `%%` en ospal.ini

---

## Ideas futuras

- Soporte multilingüe - gettext con archivos .po (sv, de, es), compilados automáticamente al inicio
- Formato configurable para correos de resumen de registros diarios
- ntfy - revisión más profunda desde una perspectiva de privacidad y legal
- Enlaces de mapas en correos de alerta - análisis de direcciones combinado con una lista de lugares configurable
- Múltiples frecuencias - escaneo o cambio entre redes
- Soporte de pantalla - mostrar alertas entrantes en una pantalla conectada

---

## Licencia

OSPAL es software libre licenciado bajo la **Licencia Pública General GNU v3.0 (GPL-3.0)**.

Consulte el archivo `LICENSE` para el texto completo de la licencia.

El código fuente está disponible en [Codeberg](https://codeberg.org).

---

## Contribuir

Los informes de errores, sugerencias y pull requests son bienvenidos en Codeberg.

# OSPAL Alert Script Specification

OSPAL can run an external Python script when a message matches a mail rule.
This allows you to trigger hardware responses such as buzzers, LEDs, or smart lights when an alert is received.

The alert script is configured in the `[alert]` section of `ospal.ini`.

---

## How it works

When a message matches a mail rule and passes duplicate suppression, OSPAL calls your script as a subprocess:

```
python3 /path/to/your/alert.py [optional argument]
```

The optional argument is controlled by `pass_message` in `ospal.ini`:

- `none` - no argument is passed
- `keyword` - the matched rule keyword is passed, e.g. `FIRE`
- `message` - the full message text is passed

Your script receives this as `sys.argv[1]` if an argument is passed.

---

## Execution modes

### queue mode

In queue mode, alerts are processed one at a time. If a new alert arrives while the script is already running, it is placed in a queue and will be processed when the current run finishes.

- Only one instance of your script runs at a time
- Alerts are never lost, but may be delayed
- `queue_max` in `ospal.ini` sets the maximum number of waiting alerts - if the queue is full, the oldest waiting alert is dropped to make room for the new one
- Your script does not need to handle signals

This mode is suitable when each alert should be handled fully and independently, and when the hardware can queue actions safely.

### interrupt mode

In interrupt mode, a new alert immediately terminates any currently running instance of your script. OSPAL sends `SIGTERM` to the running process, waits up to 2 seconds for it to exit cleanly, then force-kills it if needed and starts a new instance with the new alert data.

- Your script should handle `SIGTERM` and clean up before exiting
- Cleanup means restoring hardware to a neutral state, e.g. turning off a LED, restoring a lamp colour, silencing a buzzer
- If your script does not handle `SIGTERM`, it will be force-killed after 2 seconds, which may leave hardware in an undefined state

This mode is suitable when the most recent alert takes priority and you do not want to queue up multiple hardware responses.

---

## SIGTERM handling

In interrupt mode your script must handle `SIGTERM`. The pattern is straightforward:

```python
import signal
import sys

def cleanup(sig, frame):
    # Put hardware back to neutral state here
    # e.g. turn off LED, restore lamp colour, silence buzzer
    sys.exit(0)

signal.signal(signal.SIGTERM, cleanup)
```

Register the handler before your main loop. When OSPAL sends `SIGTERM`, your cleanup function runs and the script exits cleanly.

---

## Timeout

The `timeout` setting in `ospal.ini` sets the maximum number of seconds your script is allowed to run. If it exceeds this limit, OSPAL terminates it with a warning in the error log. Set this generously - longer than the longest sequence your script could reasonably run.

---

## Configuration reference

```ini
[alert]
enabled = false
script = /home/pi/ospal/alert.py
mode = interrupt        ; queue or interrupt
timeout = 600           ; maximum run time in seconds
pass_message = message  ; none, keyword or message
queue_max = 1           ; maximum queued alerts (queue mode only)
```

---

## Raspberry Pi GPIO

The example scripts use the `RPi.GPIO` library. Install it if not already present:

```bash
pip install RPi.GPIO --break-system-packages
```

Pin numbering in the examples uses `GPIO.BCM` (Broadcom chip numbering).
Connect your LED between the chosen GPIO pin and ground via a suitable resistor (330 ohm is a safe starting point for a standard LED at 3.3V).

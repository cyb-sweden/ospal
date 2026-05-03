#!/usr/bin/env python3
"""
example_queue.py - OSPAL alert script example for queue mode

Blinks SOS in Morse code on a GPIO LED pin, then turns the LED off.
Designed for use with mode = queue in ospal.ini.

In queue mode this script runs to completion before the next alert is processed.
No signal handling is needed.

Configuration:
  Set GPIO_PIN to the BCM pin number your LED is connected to.
  Set REPETITIONS to the number of times SOS is repeated.
  Set WPM to control Morse code speed (words per minute).
"""

import RPi.GPIO as GPIO
import time
import sys

# ── Configuration ─────────────────────────────────────────────────────────────

GPIO_PIN    = 17    # BCM pin number for LED
REPETITIONS = 3     # Number of times to repeat SOS
WPM         = 15    # Morse code speed in words per minute

# ── Morse timing ──────────────────────────────────────────────────────────────
# Standard Morse timing is based on the dot duration.
# At WPM words per minute, dot duration = 1.2 / WPM seconds.

DOT      = 1.2 / WPM        # Duration of a dot
DASH     = DOT * 3           # Duration of a dash
SYMBOL   = DOT               # Gap between symbols within a letter
LETTER   = DOT * 3           # Gap between letters
WORD     = DOT * 7           # Gap between words (used between repetitions)

# SOS: ... --- ...
SOS = [
    'dot', 'dot', 'dot',      # S
    'letter',
    'dash', 'dash', 'dash',   # O
    'letter',
    'dot', 'dot', 'dot',      # S
]


def setup():
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(GPIO_PIN, GPIO.OUT, initial=GPIO.LOW)


def led_on():
    GPIO.output(GPIO_PIN, GPIO.HIGH)


def led_off():
    GPIO.output(GPIO_PIN, GPIO.LOW)


def blink_dot():
    led_on()
    time.sleep(DOT)
    led_off()
    time.sleep(SYMBOL)


def blink_dash():
    led_on()
    time.sleep(DASH)
    led_off()
    time.sleep(SYMBOL)


def play_sos():
    for symbol in SOS:
        if symbol == 'dot':
            blink_dot()
        elif symbol == 'dash':
            blink_dash()
        elif symbol == 'letter':
            # Letter gap replaces the trailing symbol gap from last blink
            time.sleep(LETTER - SYMBOL)


def cleanup():
    led_off()
    GPIO.cleanup()


def main():
    message = sys.argv[1] if len(sys.argv) > 1 else None
    if message:
        print(f"[alert] Triggered by: {message}")

    setup()

    try:
        for i in range(REPETITIONS):
            print(f"[alert] SOS repetition {i + 1} of {REPETITIONS}")
            play_sos()
            if i < REPETITIONS - 1:
                time.sleep(WORD)
    finally:
        cleanup()
        print("[alert] Done.")


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
example_interrupt.py - OSPAL alert script example for interrupt mode

Blinks SOS in Morse code on a GPIO LED pin, then turns the LED off.
Designed for use with mode = interrupt in ospal.ini.

In interrupt mode OSPAL sends SIGTERM to this script when a new alert arrives.
The signal handler ensures the LED is turned off cleanly before exiting,
regardless of where in the sequence the script is interrupted.

Configuration:
  Set GPIO_PIN to the BCM pin number your LED is connected to.
  Set REPETITIONS to the number of times SOS is repeated.
  Set WPM to control Morse code speed (words per minute).
"""

import RPi.GPIO as GPIO
import signal
import time
import sys

# ── Configuration ─────────────────────────────────────────────────────────────

GPIO_PIN    = 17    # BCM pin number for LED
REPETITIONS = 3     # Number of times to repeat SOS
WPM         = 15    # Morse code speed in words per minute

# ── Morse timing ──────────────────────────────────────────────────────────────

DOT      = 1.2 / WPM
DASH     = DOT * 3
SYMBOL   = DOT
LETTER   = DOT * 3
WORD     = DOT * 7

SOS = [
    'dot', 'dot', 'dot',
    'letter',
    'dash', 'dash', 'dash',
    'letter',
    'dot', 'dot', 'dot',
]

# ── GPIO setup ────────────────────────────────────────────────────────────────

gpio_ready = False


def setup():
    global gpio_ready
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(GPIO_PIN, GPIO.OUT, initial=GPIO.LOW)
    gpio_ready = True


def led_on():
    GPIO.output(GPIO_PIN, GPIO.HIGH)


def led_off():
    GPIO.output(GPIO_PIN, GPIO.LOW)


def cleanup():
    if gpio_ready:
        led_off()
        GPIO.cleanup()


# ── SIGTERM handler ───────────────────────────────────────────────────────────
# OSPAL sends SIGTERM when a new alert arrives and interrupt mode is active.
# This handler turns the LED off and exits cleanly.

def handle_sigterm(sig, frame):
    print("[alert] Received SIGTERM - cleaning up and exiting.")
    cleanup()
    sys.exit(0)


signal.signal(signal.SIGTERM, handle_sigterm)


# ── Morse playback ────────────────────────────────────────────────────────────

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
            time.sleep(LETTER - SYMBOL)


# ── Main ──────────────────────────────────────────────────────────────────────

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

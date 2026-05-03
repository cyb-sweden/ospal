#!/usr/bin/env python3
"""
example_interrupt_keyword.py - OSPAL alert script example for interrupt mode

Blinks the alert keyword passed by OSPAL as Morse code on a GPIO LED pin.
If no keyword is passed, or if the keyword contains characters not in the
Morse alphabet, falls back to blinking SOS.

Designed for use with mode = interrupt and pass_message = keyword in ospal.ini.

OSPAL passes the matched rule keyword as sys.argv[1], e.g. "FIRE" or "BRAND".
Swedish characters are transliterated before encoding:
  Ä -> A, Ö -> O, Å -> A

Configuration:
  Set GPIO_PIN to the BCM pin number your LED is connected to.
  Set REPETITIONS to the number of times the keyword is repeated.
  Set WPM to control Morse code speed (words per minute).
"""

import RPi.GPIO as GPIO
import signal
import time
import sys

# ── Configuration ─────────────────────────────────────────────────────────────

GPIO_PIN    = 17    # BCM pin number for LED
REPETITIONS = 3     # Number of times to repeat the keyword
WPM         = 15    # Morse code speed in words per minute

# ── Morse timing ──────────────────────────────────────────────────────────────

DOT    = 1.2 / WPM
DASH   = DOT * 3
SYMBOL = DOT
LETTER = DOT * 3
WORD   = DOT * 7

# ── Morse alphabet ────────────────────────────────────────────────────────────

MORSE = {
    'A': '.-',   'B': '-...', 'C': '-.-.',  'D': '-..',
    'E': '.',    'F': '..-.',  'G': '--.',   'H': '....',
    'I': '..',   'J': '.---',  'K': '-.-',   'L': '.-..',
    'M': '--',   'N': '-.',    'O': '---',   'P': '.--.',
    'Q': '--.-',  'R': '.-.',   'S': '...',   'T': '-',
    'U': '..-',  'V': '...-',  'W': '.--',   'X': '-..-',
    'Y': '-.--', 'Z': '--..',
    '0': '-----', '1': '.----', '2': '..---', '3': '...--',
    '4': '....-', '5': '.....', '6': '-....', '7': '--...',
    '8': '---..',  '9': '----.',
}

# Swedish character transliteration
TRANSLITERATE = {
    'Ä': 'A', 'Ö': 'O', 'Å': 'A',
    'ä': 'A', 'ö': 'O', 'å': 'A',
}

SOS_PATTERN = '... --- ...'


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


def blink_letter(pattern):
    """Blinks a single Morse pattern string e.g. '.-.'"""
    for i, symbol in enumerate(pattern):
        if symbol == '.':
            blink_dot()
        elif symbol == '-':
            blink_dash()
    # Replace trailing symbol gap with letter gap
    time.sleep(LETTER - SYMBOL)


def blink_text(text):
    """Blinks a full text string in Morse code."""
    for letter in text.upper():
        if letter in MORSE:
            blink_letter(MORSE[letter])
        # Non-Morse characters (spaces etc.) are silently skipped


def prepare_keyword(keyword):
    """
    Transliterates Swedish characters and checks that all remaining
    characters are in the Morse alphabet.
    Returns the prepared string, or None if it cannot be encoded.
    """
    prepared = ''
    for ch in keyword.upper():
        if ch in TRANSLITERATE:
            prepared += TRANSLITERATE[ch]
        else:
            prepared += ch

    if all(ch in MORSE for ch in prepared.upper()):
        return prepared
    return None


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    raw_keyword = sys.argv[1] if len(sys.argv) > 1 else None

    if raw_keyword:
        prepared = prepare_keyword(raw_keyword)
        if prepared:
            text = prepared
            print(f"[alert] Blinking keyword: {raw_keyword} -> {text}")
        else:
            text = None
            print(f"[alert] Keyword '{raw_keyword}' contains unencodable characters - falling back to SOS.")
    else:
        text = None
        print("[alert] No keyword received - falling back to SOS.")

    setup()

    try:
        for i in range(REPETITIONS):
            print(f"[alert] Repetition {i + 1} of {REPETITIONS}")
            if text:
                blink_text(text)
            else:
                blink_text('SOS')
            if i < REPETITIONS - 1:
                time.sleep(WORD)
    finally:
        cleanup()
        print("[alert] Done.")


if __name__ == '__main__':
    main()

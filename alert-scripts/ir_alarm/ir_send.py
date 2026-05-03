#!/usr/bin/env python3
"""
ir_send.py — IR Remote Control Signal Sender

Sends a single IR signal from a mapping file created by ir_learn.py.
The file and button name can be supplied as positional arguments on the
command line, or the script will prompt for them interactively.

Usage:
    python3 ir_send.py <file> <button>
    python3 ir_send.py <file>
    python3 ir_send.py
    python3 ir_send.py --help

The .txt extension on the filename is optional. Button names are matched
case-insensitively.
"""

import os
import sys
import argparse
import pigpio
import time


# ──────────────────────────────────────────────────────────────────────────────
# GPIO and carrier constants
# ──────────────────────────────────────────────────────────────────────────────

# The IR transmitter DATA pin connects to GPIO 18 (physical pin 12).
# GPIO 18 is chosen specifically because it supports hardware PWM, which
# is used to generate the 38kHz carrier signal accurately without burdening
# the CPU with software timing loops.
IR_TX_GPIO = 18

# Standard IR carrier frequency used by NEC and most common protocols.
# The transmitter module modulates the IR LED at this frequency during
# each mark (burst) period.
CARRIER_HZ = 38000


# ──────────────────────────────────────────────────────────────────────────────
# Pulse decoding
# ──────────────────────────────────────────────────────────────────────────────

def decode_pulses(code):
    """
    Convert a pulse fingerprint string from the mapping file back into a
    list of (duration_us, level) tuples ready for transmission.

    The fingerprint format is described in ir_learn.py. Briefly, each token
    is <duration><flag> where flag is 'L' (mark, carrier on) or 'H' (space,
    carrier off). The level values used here match what send_ir() expects:
      level 1 = mark  = transmitter should burst carrier
      level 0 = space = transmitter should stay silent

    Note on polarity: the mapping file stores signals as seen by the IR
    receiver, which is active low. 'L' in the file means the receiver saw
    the carrier — so when replaying we must transmit carrier for 'L' tokens
    and silence for 'H' tokens.
    """
    pulses = []
    for token in code.strip().split(":"):
        if not token:
            continue
        level = 1 if token[-1] == "L" else 0
        dur   = int(token[:-1])
        pulses.append((dur, level))
    return pulses


# ──────────────────────────────────────────────────────────────────────────────
# Mapping file loading
# ──────────────────────────────────────────────────────────────────────────────

def load_mapping(filepath):
    """
    Load a button name to pulse fingerprint mapping from a txt file.

    The file is produced by ir_learn.py. Each non-comment line has the form:
        BUTTON_NAME = <pulse fingerprint>

    Lines starting with '#' and blank lines are ignored. Button names are
    returned exactly as stored — case-insensitive lookup is handled by the
    caller via find_button().
    """
    mapping = {}
    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            button, _, code = line.partition("=")
            mapping[button.strip()] = code.strip()
    return mapping


# ──────────────────────────────────────────────────────────────────────────────
# IR transmission
# ──────────────────────────────────────────────────────────────────────────────

def send_ir(pi, pulses):
    """
    Transmit a pulse sequence on IR_TX_GPIO using pigpio waveforms.

    How it works
    ------------
    pigpio waveforms let us schedule precise GPIO transitions in advance.
    For each mark (level=1) we generate a series of rapid on/off toggles
    at the carrier frequency, which causes the IR LED to flash at 38kHz
    as expected by the receiving device. For each space (level=0) we
    simply hold the GPIO low for the required duration.

    The waveform is uploaded to the pigpio daemon and played back with
    hardware-level timing accuracy, independent of Python's scheduler.

    Parameters
    ----------
    pi     : connected pigpio.pi() instance
    pulses : list of (duration_us, level) from decode_pulses()
    """
    pi.wave_clear()

    # Calculate the period of one carrier cycle and split it in half for
    # the on and off portions of each 38kHz toggle.
    period_us = int(1_000_000 / CARRIER_HZ)
    half      = period_us // 2

    wave_pulses = []
    for duration_us, level in pulses:
        if level == 1:
            # Mark: generate carrier bursts by toggling the GPIO on and off
            # at the carrier frequency for the required duration.
            cycles = max(1, duration_us // period_us)
            for _ in range(cycles):
                wave_pulses.append(pigpio.pulse(1 << IR_TX_GPIO, 0,              half))
                wave_pulses.append(pigpio.pulse(0,              1 << IR_TX_GPIO, half))
        else:
            # Space: hold the GPIO low (transmitter off) for the full duration.
            wave_pulses.append(pigpio.pulse(0, 1 << IR_TX_GPIO, duration_us))

    if not wave_pulses:
        print("  ERROR: No pulses to send.")
        return

    pi.wave_add_generic(wave_pulses)
    wave_id = pi.wave_create()

    if wave_id < 0:
        print(f"  ERROR: Could not create wave (code {wave_id}).")
        return

    pi.wave_send_once(wave_id)

    # Block until the waveform has finished transmitting before returning.
    while pi.wave_tx_busy():
        time.sleep(0.001)

    pi.wave_delete(wave_id)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def resolve_filepath(name):
    """
    Given a filename (with or without .txt extension), return the full
    absolute path resolved relative to the script's own directory.

    Keeping files in the script directory means ir_send.py, ir_learn.py,
    and ir_alarm.py can all find mapping files by name alone.
    """
    if not name.endswith(".txt"):
        name += ".txt"
    if not os.path.isabs(name):
        name = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
    return name


def find_button(mapping, name):
    """
    Look up a button by name, falling back to a case-insensitive search.

    Returns the key as stored in the mapping dict, or None if not found.
    This means the user can type 'power' and match a button stored as 'POWER'.
    """
    if name in mapping:
        return name
    return next((b for b in mapping if b.lower() == name.lower()), None)


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="ir_send.py",
        description="Send a single IR button signal from a mapping file.",
        epilog=(
            "examples:\n"
            "  python3 ir_send.py myremote POWER\n"
            "  python3 ir_send.py myremote.txt vol_up\n"
            "  python3 ir_send.py myremote        (prompts for button)\n"
            "  python3 ir_send.py                 (fully interactive)"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "file",
        nargs="?",
        help="mapping file name (with or without .txt extension)",
    )
    parser.add_argument(
        "button",
        nargs="?",
        help="button name to send (case-insensitive)",
    )
    args = parser.parse_args()

    print("=" * 50)
    print("  IR Remote Control Signal Sender")
    print("=" * 50)
    print(f"  Transmitter : GPIO {IR_TX_GPIO} (pin 12)")

    # ── Resolve mapping file ──────────────────────────────────────────────────

    if args.file:
        # File was given on the command line — fail immediately if not found
        # rather than dropping into an interactive prompt unexpectedly.
        filepath = resolve_filepath(args.file)
        if not os.path.exists(filepath):
            print(f"ERROR: File not found: {filepath}")
            sys.exit(1)
    else:
        # No file argument — ask interactively and keep asking until a valid
        # file name is entered.
        while True:
            name = input("\nEnter mapping file name: ").strip()
            if not name:
                print("  Filename cannot be empty.")
                continue
            filepath = resolve_filepath(name)
            if os.path.exists(filepath):
                break
            print(f"  File not found: {filepath}")

    mapping = load_mapping(filepath)
    if not mapping:
        print("ERROR: No buttons found in that file.")
        sys.exit(1)

    print(f"\nLoaded {len(mapping)} button(s) from '{os.path.basename(filepath)}':")
    for btn in mapping:
        print(f"  {btn}")

    # ── Resolve button name ───────────────────────────────────────────────────

    if args.button:
        # Button was given on the command line — fail with a clear error and
        # the full button list if it cannot be found.
        button = find_button(mapping, args.button)
        if not button:
            print(f"\nERROR: Button '{args.button}' not found.")
            print("Available buttons:")
            for btn in mapping:
                print(f"  {btn}")
            sys.exit(1)
    else:
        # No button argument — ask interactively and keep asking until a
        # valid button name is entered.
        while True:
            name   = input("\nEnter button name to send: ").strip()
            button = find_button(mapping, name)
            if button:
                break
            print(f"  '{name}' not found. Available buttons:")
            for btn in mapping:
                print(f"    {btn}")

    # ── Connect to pigpio ─────────────────────────────────────────────────────

    print("\nConnecting to pigpio daemon...")
    pi = pigpio.pi()
    if not pi.connected:
        print("ERROR: Could not connect to pigpio daemon.")
        print("  Make sure it is running:  sudo pigpiod")
        sys.exit(1)

    pi.set_mode(IR_TX_GPIO, pigpio.OUTPUT)

    # Ensure the transmitter is off before we start to avoid sending a
    # spurious partial signal if the pin was left high by a previous run.
    pi.write(IR_TX_GPIO, 0)

    # ── Send ──────────────────────────────────────────────────────────────────

    pulses = decode_pulses(mapping[button])
    print(f"\nSending '{button}'  ({len(pulses)} pulses)...")
    send_ir(pi, pulses)
    print("Done.")

    # Ensure the transmitter is off after sending. If send_ir() returns
    # mid-waveform for any reason this prevents the LED staying lit.
    pi.write(IR_TX_GPIO, 0)
    pi.stop()


if __name__ == "__main__":
    main()

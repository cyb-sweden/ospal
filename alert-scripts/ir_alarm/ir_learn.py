#!/usr/bin/env python3
"""
ir_learn.py — IR Remote Control Signal Learner

Listens on the IR receiver (GPIO 23, pin 16) for signals from a remote
control. After each button press is detected, the captured signal is
displayed and the user is asked to give it a name. All named signals are
saved to a txt file that can be used by ir_send.py and ir_alarm.py.

Usage:
    python3 ir_learn.py

The script will ask for a filename at startup. If the file already exists
it will ask whether to overwrite it. Press Ctrl-C at any time to stop
capturing and save whatever has been recorded so far.
"""

import os
import sys
import signal
import pigpio
import time


# ──────────────────────────────────────────────────────────────────────────────
# GPIO and timing constants
# ──────────────────────────────────────────────────────────────────────────────

# The IR receiver OUT pin connects to GPIO 23 (physical pin 16).
# The receiver output is active low — it pulls LOW when IR carrier is present.
IR_RX_GPIO = 23

# Pulses shorter than this are considered electrical noise and ignored.
# 100 microseconds is safe for NEC and most other common IR protocols.
GLITCH_US = 100

# After the last pulse edge, we wait this long (in milliseconds) before
# declaring the burst finished. Most IR protocols finish well within 5ms
# of silence, but increase this if signals are getting cut short.
TIMEOUT_MS = 5


# ──────────────────────────────────────────────────────────────────────────────
# Shared state for the pigpio callback
#
# pigpio callbacks run in a background thread, so these globals are the
# simplest way to pass data back to the main loop without a queue.
# ──────────────────────────────────────────────────────────────────────────────

# Accumulates (duration_us, level) tuples while a burst is being received.
pulses = []

# Set to True by the callback when the first edge of a new burst arrives.
# The main loop spins on this flag waiting for activity.
recording = False

# The pigpio tick value of the most recently seen edge. Used to calculate
# pulse durations and to detect end-of-burst silence.
last_tick = None

# The pigpio connection object. Kept as a global so cleanup() can reach it.
pi = None

# The callback handle returned by pi.callback(). Kept so it can be cancelled
# cleanly on exit without leaving orphaned callbacks running.
cb_handle = None


# ──────────────────────────────────────────────────────────────────────────────
# Callback
# ──────────────────────────────────────────────────────────────────────────────

def pulse_callback(gpio, level, tick):
    """
    Called by pigpio on every rising or falling edge on the IR receiver pin.

    Parameters
    ----------
    gpio  : the GPIO number that triggered (always IR_RX_GPIO here)
    level : 0 = falling edge (carrier on), 1 = rising edge (carrier off)
    tick  : pigpio timestamp in microseconds (wraps at 2^32)

    The first call in a new burst just records the starting tick so the
    next call can calculate the duration of the first pulse. Subsequent
    calls calculate pulse duration from the previous tick and append to
    the global pulses list.
    """
    global pulses, recording, last_tick

    if last_tick is None:
        # First edge of a new burst — record start time and signal the
        # main loop that we have started receiving.
        last_tick = tick
        recording = True
        return

    duration = pigpio.tickDiff(last_tick, tick)
    last_tick = tick

    if duration < GLITCH_US:
        # Discard very short pulses — these are typically electrical glitches
        # on the line rather than real IR signal edges.
        return

    pulses.append((duration, level))
    recording = True


# ──────────────────────────────────────────────────────────────────────────────
# Encoding
# ──────────────────────────────────────────────────────────────────────────────

def encode_pulses(pulse_list):
    """
    Convert a list of (duration_us, level) tuples into a compact string
    fingerprint suitable for storage in the mapping txt file.

    Encoding format
    ---------------
    Each pulse becomes a token of the form <duration><flag> where:
      - <duration> is the pulse length in microseconds, quantised to the
        nearest 50us to absorb minor timing jitter between presses.
      - <flag> is 'L' when the receiver pin was LOW (IR carrier present,
        i.e. a mark) and 'H' when it was HIGH (silence, i.e. a space).

    Tokens are joined with ':' separators, for example:
      9000L:4500H:550L:550H:600L:550H:...

    This encoding is intentionally human-readable so the mapping file can
    be inspected and edited in a text editor if needed.
    """
    quantised = []
    for dur, lvl in pulse_list:
        # Round to the nearest 50us bucket to smooth out jitter
        q = int(round(dur / 50.0)) * 50
        quantised.append(f"{q}{'H' if lvl == 0 else 'L'}")
    return ":".join(quantised)


# ──────────────────────────────────────────────────────────────────────────────
# File handling
# ──────────────────────────────────────────────────────────────────────────────

def get_filename():
    """
    Prompt the user for an output filename and return the full path.

    The file is always placed in the same directory as this script so that
    ir_send.py and ir_alarm.py can find it by name without needing a path.

    If the user omits the .txt extension it is added automatically.
    If a file with the chosen name already exists the user is asked whether
    to overwrite it. If they decline they are asked to choose again.
    """
    while True:
        name = input("\nEnter output filename (without extension): ").strip()

        if not name:
            print("  Filename cannot be empty, please try again.")
            continue

        filename = name if name.endswith(".txt") else name + ".txt"
        filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)

        if os.path.exists(filepath):
            answer = input(f"  '{filename}' already exists. Overwrite? [y/N]: ").strip().lower()
            if answer == "y":
                return filepath
            else:
                print("  Please choose a different filename.")
        else:
            return filepath


def save_mapping(filepath, mapping):
    """
    Write the button name to pulse fingerprint mapping to a txt file.

    The file format is one entry per line:
        BUTTON_NAME = <pulse fingerprint>

    Lines beginning with '#' are comments and are ignored by the loader.
    The format is intentionally simple so it can be read and edited by hand.
    """
    with open(filepath, "w") as f:
        f.write("# IR Remote Button Mapping\n")
        f.write("# Generated by ir_learn.py\n")
        f.write("# Format: BUTTON_NAME = <pulse fingerprint>\n")
        f.write("#\n")
        f.write("# Each token in the fingerprint is <duration_us><H|L> where:\n")
        f.write("#   L = receiver LOW  = IR carrier present (mark)\n")
        f.write("#   H = receiver HIGH = silence (space)\n")
        f.write("\n")
        for button, code in mapping.items():
            f.write(f"{button} = {code}\n")
    print(f"\nMapping saved to: {filepath}")


# ──────────────────────────────────────────────────────────────────────────────
# Signal handling and cleanup
# ──────────────────────────────────────────────────────────────────────────────

def handle_sigint(signum, frame):
    """
    SIGINT handler (Ctrl-C).

    Rather than calling sys.exit() directly here — which would bypass the
    file-saving code in main() — we raise KeyboardInterrupt so that the
    try/except block in main() catches it, saves the file, and then calls
    cleanup() in the normal flow.
    """
    raise KeyboardInterrupt


def cleanup():
    """
    Release pigpio resources and exit cleanly.

    Always called as the last step after saving, never directly from the
    signal handler, to ensure the mapping file is written first.
    """
    global pi, cb_handle
    print("Shutting down...")
    if cb_handle:
        cb_handle.cancel()
    if pi and pi.connected:
        pi.stop()
    sys.exit(0)


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main():
    global pulses, recording, last_tick, pi, cb_handle

    print("=" * 50)
    print("  IR Remote Control Signal Learner")
    print("=" * 50)
    print(f"  Receiver    : GPIO {IR_RX_GPIO} (pin 16)")
    print(f"  TX reserved : GPIO 18 (pin 12)")

    # Ask for the output filename before doing anything else so the user
    # does not have to sit through the setup only to be asked at the end.
    filepath = get_filename()
    print(f"\nWill save to: {os.path.basename(filepath)}")

    # Connect to the pigpio daemon. The daemon must already be running.
    # Start it with: sudo pigpiod
    print("\nConnecting to pigpio daemon...")
    pi = pigpio.pi()
    if not pi.connected:
        print("ERROR: Could not connect to pigpio daemon.")
        print("  Make sure it is running:  sudo pigpiod")
        sys.exit(1)

    # Configure the receiver pin as a pulled-up input. The IR receiver
    # output is open-drain style — it pulls low on signal and floats high
    # during silence, so the pull-up keeps the line stable when idle.
    pi.set_mode(IR_RX_GPIO, pigpio.INPUT)
    pi.set_pull_up_down(IR_RX_GPIO, pigpio.PUD_UP)

    # Register the edge callback on both rising and falling edges so we
    # capture the full pulse shape, not just one side of each transition.
    cb_handle = pi.callback(IR_RX_GPIO, pigpio.EITHER_EDGE, pulse_callback)

    # Install the Ctrl-C handler after pigpio is set up so cleanup() has
    # a valid pi object to work with if the user quits immediately.
    signal.signal(signal.SIGINT, handle_sigint)

    mapping = {}
    print("\nReady. Point your remote at the sensor and press buttons.")
    print("Press Ctrl-C at any time to stop and save.\n")

    try:
        while True:
            # Reset burst state before waiting for the next button press.
            pulses    = []
            recording = False
            last_tick = None

            # Spin until the callback signals that an edge has been seen.
            print("Waiting for signal...", end="\r", flush=True)
            while not recording:
                time.sleep(0.01)

            # The callback is now accumulating pulses. Poll until we see
            # a silence gap longer than TIMEOUT_MS, which marks the end
            # of the current IR burst.
            while True:
                time.sleep(0.001)
                if not pulses:
                    continue
                now = pigpio.tickDiff(last_tick, pi.get_current_tick())
                if now > TIMEOUT_MS * 1000:
                    break

            captured = list(pulses)

            # Fewer than 4 pulses is almost certainly noise rather than
            # a real IR frame, so discard without prompting the user.
            if len(captured) < 4:
                continue

            code = encode_pulses(captured)
            print(f"\nSignal captured!  ({len(captured)} pulses)")
            print(f"  Code: {code[:60]}{'...' if len(code) > 60 else ''}")

            # Warn if this signal matches one already recorded — the user
            # may have pressed the same button twice by accident.
            existing = [btn for btn, c in mapping.items() if c == code]
            if existing:
                print(f"  (This looks like a repeat of: {', '.join(existing)})")

            name = input("  Name this button (or press Enter to skip): ").strip()
            if name:
                mapping[name] = code
                print(f"  Saved as '{name}'  ({len(mapping)} button(s) recorded so far)")
            else:
                print("  Skipped.")

            print()

    except KeyboardInterrupt:
        pass

    # Save whatever was recorded before releasing pigpio resources.
    if mapping:
        save_mapping(filepath, mapping)
    else:
        print("\nNo buttons were recorded — nothing saved.")

    cleanup()


if __name__ == "__main__":
    main()

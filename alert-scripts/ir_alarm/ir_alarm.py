#!/usr/bin/env python3
"""
ir_alarm.py — IR Sequence Sender

Sends sequences of IR buttons, pauses, and repeats as defined in
ir_alarm.ini. A trigger word is passed as a command line argument and
the corresponding sequence from the ini file is executed.

Each trigger word section in the ini file supports four optional keys:

    pre          — steps to run once before the repeated block
    steps        — steps to repeat (see repetitions)
    repetitions  — how many times to repeat the steps block (default 1)
    post         — steps to run once after the repeated block

A default_pause is applied between every step, between pre and the first
repetition, between repetitions, and between the last repetition and post.

Usage:
    python3 ir_alarm.py <word>
    python3 ir_alarm.py --list
    python3 ir_alarm.py --help
    python3 ir_alarm.py          (prompts interactively)

The ini file must be named ir_alarm.ini and placed in the same directory
as this script.
"""

import os
import sys
import time
import argparse
import configparser
import pigpio


# ──────────────────────────────────────────────────────────────────────────────
# GPIO and carrier constants
# ──────────────────────────────────────────────────────────────────────────────

# The IR transmitter DATA pin connects to GPIO 18 (physical pin 12).
# GPIO 18 supports hardware PWM which is used to generate the 38kHz
# carrier signal accurately without burdening the CPU.
IR_TX_GPIO = 18

# Standard IR carrier frequency used by NEC and most common protocols.
CARRIER_HZ = 38000

# Path to the ini file, expected alongside this script.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INI_FILE   = os.path.join(SCRIPT_DIR, "ir_alarm.ini")


# ──────────────────────────────────────────────────────────────────────────────
# Pulse helpers
#
# These functions are duplicated from ir_send.py rather than imported so that
# each script remains self-contained and can be run independently without
# requiring the other files to be present.
# ──────────────────────────────────────────────────────────────────────────────

def decode_pulses(code):
    """
    Convert a pulse fingerprint string from the mapping file into a list
    of (duration_us, level) tuples ready for transmission.

    The mapping file stores signals as seen by the IR receiver (active low).
    'L' means the receiver saw carrier, so when replaying we transmit carrier.
    'H' means silence, so we hold the transmitter off.

    level 1 = mark  = transmit carrier burst
    level 0 = space = hold transmitter off
    """
    pulses = []
    for token in code.strip().split(":"):
        if not token:
            continue
        level = 1 if token[-1] == "L" else 0
        dur   = int(token[:-1])
        pulses.append((dur, level))
    return pulses


def load_mapping(filepath):
    """
    Load a button name to pulse fingerprint mapping from a txt file produced
    by ir_learn.py. Lines beginning with '#' and blank lines are skipped.
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


def send_ir(pi, pulses):
    """
    Transmit a pulse sequence on IR_TX_GPIO using pigpio waveforms.

    For each mark (level=1) a series of rapid on/off GPIO toggles at the
    carrier frequency is generated, causing the IR LED to burst at 38kHz.
    For each space (level=0) the GPIO is held low for the required duration.

    The waveform is played back with hardware-level timing accuracy by the
    pigpio daemon, independent of Python scheduling delays.
    """
    pi.wave_clear()

    period_us = int(1_000_000 / CARRIER_HZ)
    half      = period_us // 2

    wave_pulses = []
    for duration_us, level in pulses:
        if level == 1:
            # Mark: toggle GPIO at carrier frequency for the burst duration
            cycles = max(1, duration_us // period_us)
            for _ in range(cycles):
                wave_pulses.append(pigpio.pulse(1 << IR_TX_GPIO, 0,              half))
                wave_pulses.append(pigpio.pulse(0,              1 << IR_TX_GPIO, half))
        else:
            # Space: hold GPIO low for the silence duration
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

    while pi.wave_tx_busy():
        time.sleep(0.001)

    pi.wave_delete(wave_id)


def find_button(mapping, name):
    """
    Look up a button by name with case-insensitive fallback.
    Returns the stored key, or None if not found.
    """
    if name in mapping:
        return name
    return next((b for b in mapping if b.lower() == name.lower()), None)


# ──────────────────────────────────────────────────────────────────────────────
# INI file loading
# ──────────────────────────────────────────────────────────────────────────────

def parse_steps(raw):
    """
    Split a comma-separated steps string into a clean list of step tokens.
    Empty tokens from trailing commas or double commas are discarded.
    """
    return [s.strip() for s in raw.split(",") if s.strip()]


def load_ini(ini_path):
    """
    Parse ir_alarm.ini and return a (settings, sequences) tuple.

    settings  : dict with keys:
                  'file'          — resolved path to the mapping txt file
                  'default_pause' — int milliseconds to pause between steps

    sequences : dict mapping lowercase trigger word to a sequence dict with:
                  'pre'          — list of step strings to run once before
                  'steps'        — list of step strings to repeat
                  'repetitions'  — int number of times to repeat steps
                  'post'         — list of step strings to run once after

    The function exits with a clear error message if the ini file is missing,
    if [settings] is absent, or if the 'file' key is not set.
    """
    if not os.path.exists(ini_path):
        print(f"ERROR: Config file not found: {ini_path}")
        sys.exit(1)

    cfg = configparser.ConfigParser()
    cfg.read(ini_path)

    if "settings" not in cfg:
        print("ERROR: [settings] section missing from ir_alarm.ini")
        sys.exit(1)

    settings = {
        "file":          cfg["settings"].get("file", "").strip(),
        "default_pause": int(cfg["settings"].get("default_pause", "200")),
    }

    if not settings["file"]:
        print("ERROR: 'file' key not set in [settings] section of ir_alarm.ini")
        sys.exit(1)

    # Resolve the mapping file path relative to the script directory so the
    # user can specify just a filename without a full path.
    if not os.path.isabs(settings["file"]):
        settings["file"] = os.path.join(SCRIPT_DIR, settings["file"])

    # Every section other than [settings] is treated as a trigger word.
    # Section names are normalised to lowercase so matching is case-insensitive.
    # All four keys (pre, steps, repetitions, post) are optional — missing keys
    # produce empty lists or a default repetition count of 1.
    sequences = {}
    for section in cfg.sections():
        if section == "settings":
            continue

        raw_repetitions = cfg[section].get("repetitions", "1").strip()
        try:
            repetitions = int(raw_repetitions)
        except ValueError:
            print(f"WARNING: Invalid repetitions value '{raw_repetitions}' "
                  f"in [{section}], defaulting to 1.")
            repetitions = 1

        sequences[section.lower()] = {
            "pre":         parse_steps(cfg[section].get("pre",   "")),
            "steps":       parse_steps(cfg[section].get("steps", "")),
            "repetitions": repetitions,
            "post":        parse_steps(cfg[section].get("post",  "")),
        }

    return settings, sequences


# ──────────────────────────────────────────────────────────────────────────────
# Step execution
# ──────────────────────────────────────────────────────────────────────────────

def execute_steps(pi, mapping, steps, default_pause_ms):
    """
    Execute a list of step strings in order.

    Supported step formats
    ----------------------
    <button>
        Send the named IR button signal. A default_pause_ms delay is applied
        after each send to give the receiving device time to process the
        signal before the next one arrives.

    pause:<ms>
        Wait for the specified number of milliseconds. Use this to insert
        longer delays than the default, for example to allow a device to
        finish changing input before the next command.

    repeat:<n>:<button>
        Send the named button n times. The default_pause_ms delay is applied
        between each repetition but not after the final one, since the
        outer loop or the next step will provide that gap.

    Unknown button names produce a warning and are skipped rather than
    aborting the whole sequence, so a typo in the ini file does not silently
    prevent the remaining steps from running.
    """
    for step in steps:
        step_lower = step.lower()

        if step_lower.startswith("pause:"):
            # Extract the millisecond value after the colon.
            # Fall back to the default if the value is missing or not a number.
            try:
                ms = int(step.split(":")[1])
            except (IndexError, ValueError):
                print(f"  WARNING: Invalid pause step '{step}', using default.")
                ms = default_pause_ms
            print(f"  Pausing {ms}ms...")
            time.sleep(ms / 1000)

        elif step_lower.startswith("repeat:"):
            # Format is repeat:<count>:<button>.
            # Split into at most 3 parts so a button name containing ':' is safe.
            parts = step.split(":", 2)
            if len(parts) != 3:
                print(f"  WARNING: Invalid repeat step '{step}', skipping.")
                continue
            try:
                count = int(parts[1])
            except ValueError:
                print(f"  WARNING: Invalid repeat count in '{step}', skipping.")
                continue
            btn_name = parts[2].strip()
            btn_key  = find_button(mapping, btn_name)
            if not btn_key:
                print(f"  WARNING: Button '{btn_name}' not found in mapping, skipping repeat.")
                continue
            for i in range(count):
                print(f"  Sending '{btn_key}' ({i + 1}/{count})...")
                send_ir(pi, decode_pulses(mapping[btn_key]))
                # Pause between repeats but not after the last one — the
                # outer flow will apply the next inter-step pause.
                if i < count - 1:
                    time.sleep(default_pause_ms / 1000)

        else:
            # Treat the step as a plain button name.
            btn_key = find_button(mapping, step)
            if not btn_key:
                print(f"  WARNING: Button '{step}' not found in mapping, skipping.")
                continue
            print(f"  Sending '{btn_key}'...")
            send_ir(pi, decode_pulses(mapping[btn_key]))
            time.sleep(default_pause_ms / 1000)


def execute_sequence(pi, mapping, sequence, default_pause_ms):
    """
    Execute a full sequence dict as loaded from the ini file.

    Execution order
    ---------------
    1. Run the pre steps once.
    2. Pause (default_pause_ms) after pre if pre is non-empty and steps follow.
    3. Run the steps block, repeating it 'repetitions' times.
       Between each repetition a default_pause_ms gap is inserted so the
       receiver has time to settle before the next cycle starts.
    4. Pause (default_pause_ms) after the last repetition if post is non-empty.
    5. Run the post steps once.

    Any of pre, steps, and post may be empty — missing blocks are silently
    skipped and their associated boundary pauses are not inserted.
    """
    pre         = sequence["pre"]
    steps       = sequence["steps"]
    repetitions = sequence["repetitions"]
    post        = sequence["post"]

    # Run the pre block if one is defined.
    if pre:
        print("  [pre]")
        execute_steps(pi, mapping, pre, default_pause_ms)
        # Insert a boundary pause between pre and the steps block so the
        # receiver has a moment to process the last pre command before
        # the repeated section begins.
        if steps:
            time.sleep(default_pause_ms / 1000)

    # Run the steps block the requested number of times.
    if steps:
        for rep in range(repetitions):
            if repetitions > 1:
                print(f"  [steps — repetition {rep + 1} of {repetitions}]")
            else:
                print("  [steps]")
            execute_steps(pi, mapping, steps, default_pause_ms)
            # Insert a boundary pause after each repetition, including after
            # the last one if a post block follows. This gives the receiver
            # a consistent settling gap regardless of what comes next.
            if rep < repetitions - 1 or post:
                time.sleep(default_pause_ms / 1000)

    # Run the post block if one is defined.
    if post:
        print("  [post]")
        execute_steps(pi, mapping, post, default_pause_ms)


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="ir_alarm.py",
        description="Send IR button sequences defined in ir_alarm.ini.",
        epilog=(
            "examples:\n"
            "  python3 ir_alarm.py brand\n"
            "  python3 ir_alarm.py off\n"
            "  python3 ir_alarm.py --list\n"
            "  python3 ir_alarm.py          (interactive)"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "word",
        nargs="?",
        help="trigger word to execute (must be defined in ir_alarm.ini)",
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="list all available trigger words and their configuration, then exit",
    )
    args = parser.parse_args()

    settings, sequences = load_ini(INI_FILE)

    # Print the full list of configured words and their blocks then exit.
    if args.list:
        print(f"Trigger words in {os.path.basename(INI_FILE)}:")
        for word, seq in sequences.items():
            print(f"\n  [{word}]")
            if seq["pre"]:
                print(f"    pre         : {', '.join(seq['pre'])}")
            print(    f"    steps       : {', '.join(seq['steps']) if seq['steps'] else '(none)'}")
            print(    f"    repetitions : {seq['repetitions']}")
            if seq["post"]:
                print(f"    post        : {', '.join(seq['post'])}")
        sys.exit(0)

    # Resolve the trigger word from the argument or interactively.
    if args.word:
        word = args.word.lower()
    else:
        word = input("Enter trigger word: ").strip().lower()

    if word not in sequences:
        print(f"ERROR: '{word}' is not defined in ir_alarm.ini.")
        print("  Run with --list to see available words.")
        sys.exit(1)

    # Verify the mapping file exists before connecting to pigpio so we get
    # a clear error message rather than a confusing pigpio failure.
    if not os.path.exists(settings["file"]):
        print(f"ERROR: Mapping file not found: {settings['file']}")
        sys.exit(1)

    mapping = load_mapping(settings["file"])
    if not mapping:
        print("ERROR: No buttons found in mapping file.")
        sys.exit(1)

    print("\nConnecting to pigpio daemon...")
    pi = pigpio.pi()
    if not pi.connected:
        print("ERROR: Could not connect to pigpio daemon.")
        print("  Make sure it is running:  sudo pigpiod")
        sys.exit(1)

    pi.set_mode(IR_TX_GPIO, pigpio.OUTPUT)

    # Ensure the transmitter LED is off before starting the sequence.
    pi.write(IR_TX_GPIO, 0)

    print(f"\nExecuting sequence for '{word}'...")
    execute_sequence(pi, mapping, sequences[word], settings["default_pause"])
    print("Done.")

    # Ensure the transmitter is off after the sequence completes.
    pi.write(IR_TX_GPIO, 0)
    pi.stop()


if __name__ == "__main__":
    main()

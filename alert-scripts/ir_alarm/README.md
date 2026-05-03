# IR Remote Control Scripts

Three Python scripts for learning, sending, and sequencing IR remote control
signals on a Raspberry Pi Zero W2.

---

## Hardware setup

| Component      | Physical pin | GPIO    | Notes                         |
|----------------|-------------|---------|-------------------------------|
| Both VCC       | 4           | —       | 5V power (shared)             |
| Both GND       | 6           | —       | Ground (shared)               |
| IR transmitter | 12          | GPIO 18 | Hardware PWM for carrier      |
| IR receiver    | 16          | GPIO 23 | Signal input                  |

GPIO 18 is used for the transmitter because it supports hardware PWM, which
generates the 38kHz carrier signal the receiving device expects with accurate
timing and no CPU overhead.

Before running any of the scripts, make sure the pigpio daemon is running:

    sudo pigpiod

To start it automatically on every boot:

    sudo systemctl enable pigpiod

---

## Installation

    sudo apt install python3-pigpio pigpio

If pigpio is not available via apt, build it from source:

    wget https://github.com/joan2937/pigpio/archive/master.zip
    unzip master.zip
    cd pigpio-master
    make
    sudo make install

---

## ir_learn.py — Learn remote buttons

Listens on the IR receiver and records button signals from a remote control.
Asks you to name each captured signal and saves everything to a txt file
that the other two scripts use as their button database.

### Usage

    python3 ir_learn.py

The script asks for a filename before starting. If a file with that name
already exists it asks whether to overwrite it. Press Ctrl-C at any time
to stop and save.

### Workflow

1. Run the script and enter a filename, for example: myremote
2. Point your remote at the sensor and press a button
3. The script prints the captured signal and asks you to name it
4. Repeat for every button you want to record
5. Press Ctrl-C — the mapping file is saved automatically

### Output file format

The mapping file is a plain text file with one button per line:

    # IR Remote Button Mapping
    POWER  = 9000L:4500H:550L:550H:...
    VOL_UP = 9000L:4500H:550L:600H:...

Lines beginning with # are comments. The pulse fingerprint after the = sign
encodes the timing of each IR pulse where L means the receiver saw carrier
and H means silence.

---

## ir_send.py — Send a single button

Sends one IR signal from a mapping file created by ir_learn.py.

### Usage

    python3 ir_send.py <file> <button>

Both arguments are optional. If omitted the script asks interactively.

    python3 ir_send.py myremote POWER
    python3 ir_send.py myremote.txt vol_up
    python3 ir_send.py myremote
    python3 ir_send.py
    python3 ir_send.py --help

The .txt extension is optional in all cases. Button names are matched
case-insensitively, so POWER, power, and Power all work.

---

## ir_alarm.py — Send sequences triggered by a word

Sends sequences of buttons, pauses, and repeats defined in ir_alarm.ini.
One trigger word maps to one sequence of steps, making it easy to automate
multi-step routines with a single command.

### Usage

    python3 ir_alarm.py <word>
    python3 ir_alarm.py --list
    python3 ir_alarm.py --help
    python3 ir_alarm.py

    python3 ir_alarm.py brand
    python3 ir_alarm.py off
    python3 ir_alarm.py --list

### ir_alarm.ini

The ini file must be named ir_alarm.ini and placed in the same folder as
ir_alarm.py. It contains a [settings] section and one section per trigger
word. See the comments inside ir_alarm.ini for full documentation of the
format.

Example:

    [settings]
    file          = myremote.txt
    default_pause = 200

    [brand]
    steps = on, pause:500, r255, pause:100, g50, pause:100, b0

    [off]
    steps = off

### Step types

| Syntax              | What it does                                        |
|---------------------|-----------------------------------------------------|
| buttonname          | Send that IR button (case-insensitive)              |
| pause:500           | Wait 500 milliseconds                               |
| repeat:3:buttonname | Send the button 3 times with default_pause between  |

Unknown button names are skipped with a warning and do not abort the
rest of the sequence.

---

## File locations

All three scripts expect mapping files and ir_alarm.ini to be in the same
directory as the scripts themselves. Running any script from a different
working directory is fine as long as the files are beside the scripts.

#!/usr/bin/env python3
# ============================================================
# OSPAL - Open Source POCSAG Alert Logger
# Version 0.7.0
# Copyright (C) 2024
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
# ============================================================

"""
OSPAL - Open Source POCSAG Alert Logger

Receives POCSAG messages via RTL-SDR, decodes them with multimon-ng,
logs to daily log files and sends selected alerts via SMTP and/or ntfy.

Usage:
  python3 -u ospal.py              Start receiver
  python3 -u ospal.py -t [min]     Calibrate dongle (PPM, gain, samplerate)
  python3 -u ospal.py -m           Send test mail
  python3 -u ospal.py -n           Send test ntfy notification
  python3 -u ospal.py -c file.ini  Use specified config file
"""

import subprocess
import configparser
import logging
import smtplib
import urllib.request
import urllib.error
import os
import re
import sys
import time
import signal
import threading
import traceback
import argparse
from datetime import datetime, date, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from logging.handlers import BaseRotatingHandler
from queue import Queue, Empty


# ── Constants ────────────────────────────────────────────────────────────────

VERSION    = '0.7.1'
START_TIME = datetime.now()

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

MIN_CALIBRATION_MINUTES     = 5
DEFAULT_CALIBRATION_MINUTES = 15
PPM_SPREAD_WARNING          = 30

LOG_LEVELS = {
    'debug':    logging.DEBUG,
    'info':     logging.INFO,
    'warning':  logging.WARNING,
    'error':    logging.ERROR,
    'critical': logging.CRITICAL,
}

NTFY_PRIORITIES = {'min': 1, 'low': 2, 'default': 3, 'high': 4, 'max': 5}

REQUIRED_CONFIG = [
    ('receiver', 'frequency',   'Receive frequency e.g. 148.7125M'),
    ('receiver', 'gain',        'Receiver gain in dB'),
    ('receiver', 'ppm',         'PPM calibration offset'),
    ('receiver', 'sample_rate', 'Sample rate in Hz'),
    ('logging',  'log_dir',     'Log file directory'),
]

DEFAULT_SUBJECT_TEMPLATE = '{keyword} - {message_preview}'
DEFAULT_BODY_TEMPLATE    = (
    '{timestamp}\n'
    '{message}\n\n'
    'Address  : {address}\n'
    'Function : {function}\n'
    'Frequency: {frequency}\n'
    'Uptime   : {uptime}\n'
    'Started  : {last_restart}\n'
    'Errors   : {errors_exist}\n'
    'OSPAL    : v{ospal_version}'
)

SILENT_RECEIVER_KEYWORD = 'OSPAL-SILENT'

# Global config reference used by find_matching_rule
config_ref = None


# ── Daily rotating log handler ───────────────────────────────────────────────

class DailyFileHandler(BaseRotatingHandler):
    """
    Creates a new log file each day at midnight.
    All log files are lazy - created only when first written to.
    Archives previous day's files to logs/archive/YYYY-MM/ at rollover.
    Reopens the file before each write in case it was deleted during operation.
    """

    def __init__(self, log_dir, suffix, archive_keep_days=0):
        self.log_dir           = log_dir
        self.suffix            = suffix
        self.archive_keep_days = archive_keep_days
        self._current_date     = date.today()
        filename = self._make_filename()
        super().__init__(filename, mode='a', encoding='utf-8', delay=True)

    def _make_filename(self):
        os.makedirs(self.log_dir, exist_ok=True)
        return os.path.join(
            self.log_dir,
            f"{date.today().strftime('%Y-%m-%d')}-{self.suffix}.log"
        )

    def _archive_dir(self, for_date):
        return os.path.join(self.log_dir, 'archive', for_date.strftime('%Y-%m'))

    def shouldRollover(self, record):
        return date.today() != self._current_date

    def doRollover(self):
        prev_date     = self._current_date
        prev_filename = self.baseFilename

        if self.stream:
            self.stream.close()
            self.stream = None

        self._current_date = date.today()
        self.baseFilename  = self._make_filename()

        archive_dir  = self._archive_dir(prev_date)
        os.makedirs(archive_dir, exist_ok=True)
        archive_path = os.path.join(archive_dir, os.path.basename(prev_filename))

        if os.path.exists(prev_filename):
            os.rename(prev_filename, archive_path)

        if self.archive_keep_days > 0:
            cutoff = date.today() - timedelta(days=self.archive_keep_days)
            _purge_old_archives(self.log_dir, cutoff)

    def emit(self, record):
        if self.stream and not os.path.exists(self.baseFilename):
            self.stream.close()
            self.stream = None
        super().emit(record)


def setup_logger(name, log_dir, suffix, level=logging.INFO, archive_keep_days=0):
    """Creates and returns a daily rotating lazy file logger."""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    if not logger.handlers:
        handler = DailyFileHandler(log_dir, suffix, archive_keep_days=archive_keep_days)
        handler.setFormatter(logging.Formatter('%(message)s'))
        logger.addHandler(handler)
    return logger


# ── Config ────────────────────────────────────────────────────────────────────

def resolve_path(path):
    """Resolves a path relative to the script directory if not absolute."""
    if os.path.isabs(path):
        return path
    return os.path.join(SCRIPT_DIR, path)


def load_config(config_path='ospal.ini'):
    """Reads config file. Exits if file is missing."""
    config = configparser.ConfigParser()
    if not os.path.exists(config_path):
        print(f"[ERROR] Config file not found: {config_path}")
        sys.exit(1)
    config.read(config_path, encoding='utf-8')
    return config


def validate_config(config):
    """
    Validates required ini keys and value constraints at startup.
    Prints clear error messages for each missing/invalid key and exits if any found.
    """
    errors = []

    for section, key, description in REQUIRED_CONFIG:
        if not config.has_section(section):
            errors.append(f"  Missing section [{section}] (needed for: {key} - {description})")
        elif not config.has_option(section, key):
            errors.append(f"  Missing [{section}] {key} - {description}")

    if config.getboolean('smtp', 'mail_enabled', fallback=False):
        for key in ['host', 'port', 'type', 'user', 'password', 'recipient']:
            if not config.has_option('smtp', key):
                errors.append(f"  Missing [smtp] {key} (required when mail_enabled = true)")
        if config.has_option('smtp', 'type'):
            if config.get('smtp', 'type').lower() not in ('ssl', 'starttls'):
                errors.append("  [smtp] type must be 'ssl' or 'starttls'")
        if config.has_option('smtp', 'port'):
            try:
                int(config.get('smtp', 'port'))
            except ValueError:
                errors.append("  [smtp] port must be a number")

    if config.getboolean('ntfy', 'ntfy_enabled', fallback=False):
        if not config.has_option('ntfy', 'url'):
            errors.append("  Missing [ntfy] url (required when ntfy_enabled = true)")
        if not config.has_option('ntfy', 'topic'):
            errors.append("  Missing [ntfy] topic (required when ntfy_enabled = true)")

    if config.has_option('logging', 'log_level'):
        level = config.get('logging', 'log_level').lower()
        if level not in LOG_LEVELS:
            errors.append(f"  [logging] log_level must be one of: {', '.join(LOG_LEVELS.keys())}")

    if config.has_section('alert') and config.getboolean('alert', 'enabled', fallback=False):
        script = config.get('alert', 'script', fallback='')
        if not script:
            errors.append("  [alert] script path is required when alert.enabled = true")
        elif not os.path.isfile(resolve_path(script)):
            errors.append(f"  [alert] script not found: {script}")

    if errors:
        print("[ERROR] Configuration errors in ospal.ini:")
        for e in errors:
            print(e)
        sys.exit(1)


def build_charset(config):
    charset = {}
    if config.has_section('charset'):
        for key, value in config.items('charset'):
            try:
                charset[int(key)] = value
            except ValueError:
                pass
    return charset


def get_charset_address_blacklist(config):
    raw = config.get('charset', 'charset_blacklist_addresses', fallback='')
    return set(int(x.strip()) for x in raw.split(',') if x.strip())


def get_charset_function_blacklist(config):
    raw = config.get('charset', 'charset_blacklist_functions', fallback='')
    return set(int(x.strip()) for x in raw.split(',') if x.strip())


def get_address_blacklist(config):
    raw = config.get('filtering', 'blacklist_addresses', fallback='')
    return set(int(x.strip()) for x in raw.split(',') if x.strip())


def get_keyword_blacklist(config):
    raw = config.get('filtering', 'blacklist_keywords', fallback='')
    return [x.strip().upper() for x in raw.split(',') if x.strip()]


# ── Archive helpers ───────────────────────────────────────────────────────────

def archive_stale_logs(log_dir, archive_keep_days=0):
    """
    At startup, moves any log files from previous dates still in the log
    directory to the archive. Handles the case where OSPAL was restarted
    before a rollover was triggered.
    """
    today    = date.today()
    suffixes = ['raw', 'filtered', 'keywords', 'smtp', 'ntfy', 'error']

    if not os.path.exists(log_dir):
        return

    for fname in os.listdir(log_dir):
        for suffix in suffixes:
            if fname.endswith(f'-{suffix}.log'):
                try:
                    file_date = date.fromisoformat(fname[:10])
                except ValueError:
                    continue
                if file_date < today:
                    archive_dir = os.path.join(log_dir, 'archive', file_date.strftime('%Y-%m'))
                    os.makedirs(archive_dir, exist_ok=True)
                    os.rename(os.path.join(log_dir, fname),
                              os.path.join(archive_dir, fname))
                    if archive_keep_days > 0:
                        _purge_old_archives(log_dir,
                                           today - timedelta(days=archive_keep_days))
                break


def _purge_old_archives(log_dir, cutoff_date):
    archive_root = os.path.join(log_dir, 'archive')
    if not os.path.exists(archive_root):
        return
    for month_dir in os.listdir(archive_root):
        month_path = os.path.join(archive_root, month_dir)
        if not os.path.isdir(month_path):
            continue
        for fname in os.listdir(month_path):
            fpath = os.path.join(month_path, fname)
            try:
                if date.fromisoformat(fname[:10]) < cutoff_date:
                    os.remove(fpath)
            except (ValueError, OSError):
                pass
        if not os.listdir(month_path):
            os.rmdir(month_path)


# ── Character mapping ─────────────────────────────────────────────────────────

def apply_charset(text, charset):
    return ''.join(charset.get(ord(ch), ch) for ch in text)


# ── Message parsing ───────────────────────────────────────────────────────────

def parse_pocsag_line(line):
    pattern = r'(POCSAG\d+): Address:\s*(\d+)\s+Function:\s*(\d+)(?:\s+(\w+):\s+(.*))?'
    m = re.match(pattern, line.strip())
    if not m:
        return None
    return {
        'type':         m.group(1),
        'address':      int(m.group(2)),
        'function':     int(m.group(3)),
        'content_type': m.group(4) or '',
        'content':      (m.group(5) or '').strip(),
    }


# ── Filtering ─────────────────────────────────────────────────────────────────

def should_blacklist(msg, address_blacklist, keyword_blacklist, filtering_enabled):
    if not filtering_enabled:
        return False
    if msg['address'] in address_blacklist:
        return True
    return any(kw in msg['content'].upper() for kw in keyword_blacklist)


# ── Mail rules ────────────────────────────────────────────────────────────────

def parse_mail_rules(config):
    if not config.has_section('mail_rules'):
        return []
    return [v.strip() for k, v in config.items('mail_rules')
            if v.strip() and not k.endswith('_priority')]


def get_rule_priority(rule_key, config):
    """Returns the ntfy priority for a given rule ini key, e.g. 'rule1'."""
    priority = config.get('mail_rules', f'{rule_key}_priority', fallback='default').lower()
    return priority if priority in NTFY_PRIORITIES else 'default'


def tokenize_rule(rule):
    rule = rule.replace('\\"', '\x00')
    tokens = []
    for part in re.split(r'\b(AND|NOT)\b', rule):
        part = part.replace('\x00', '"').strip()
        if part in ('AND', 'NOT'):
            tokens.append(part)
        elif part:
            tokens.append(part)
    return tokens


def evaluate_rule(rule, msg):
    content_upper = msg['content'].upper()

    if rule.strip().startswith('ADDRESS:'):
        try:
            return msg['address'] == int(rule.strip().split(':')[1])
        except (ValueError, IndexError):
            return False

    tokens  = tokenize_rule(rule)
    result  = None
    negate  = False
    combine = None

    for token in tokens:
        if token == 'AND':
            combine = 'AND'
            continue
        if token == 'NOT':
            negate = True
            continue
        if token.startswith('ADDRESS:'):
            try:
                match = (msg['address'] == int(token.split(':')[1]))
            except (ValueError, IndexError):
                match = False
        else:
            match = token.upper() in content_upper

        if negate:
            match  = not match
            negate = False
        if result is None:
            result = match
        elif combine == 'AND':
            result  = result and match
            combine = None

    return bool(result)


def find_matching_rule(msg, rules):
    """
    Returns (rule_value, rule_key) for the first matching rule, or (None, None).
    rule_key is the ini key name e.g. 'rule1', used for priority lookup.
    """
    if not config_ref or not config_ref.has_section('mail_rules'):
        return None, None
    for k, v in config_ref.items('mail_rules'):
        v = v.strip()
        if not v or k.endswith('_priority'):
            continue
        if evaluate_rule(v, msg):
            return v, k
    return None, None


# ── Duplicate suppression ─────────────────────────────────────────────────────

class DuplicateSuppressor:
    """
    Suppresses duplicate alerts for messages with similar content within
    a time window. Uses substring matching on charset-mapped text with
    NUL and control characters stripped before comparison.
    """

    def __init__(self, enabled=True, window_seconds=120, match_chars=32):
        self.enabled     = enabled
        self.window      = window_seconds
        self.match_chars = match_chars
        self._history    = []

    def _clean_history(self):
        cutoff = time.time() - self.window
        self._history = [(c, t) for c, t in self._history if t > cutoff]

    @staticmethod
    def _strip_control(text):
        return re.sub(r'[\x00-\x1f\x7f]', '', text)

    def is_duplicate(self, content):
        if not self.enabled or not content:
            return False
        content = self._strip_control(content)
        if len(content) < self.match_chars:
            return False
        self._clean_history()
        for prev, _ in self._history:
            for i in range(len(content) - self.match_chars + 1):
                if content[i:i + self.match_chars] in prev:
                    return True
        return False

    def record(self, content):
        self._clean_history()
        self._history.append((self._strip_control(content), time.time()))


# ── Alert script runner ───────────────────────────────────────────────────────

class AlertRunner:
    """
    Runs an external alert script when a matching message is received.
    mode = 'queue'     - messages queued, script runs one at a time
    mode = 'interrupt' - new alert sends SIGTERM to running script, then starts fresh
    """

    def __init__(self, script, mode, timeout, pass_message, queue_max, error_logger):
        self.script       = resolve_path(script)
        self.mode         = mode
        self.timeout      = timeout
        self.pass_message = pass_message
        self.queue_max    = queue_max
        self.error_logger = error_logger
        self._proc        = None
        self._thread      = None
        self._queue       = Queue(maxsize=queue_max)
        self._lock        = threading.Lock()

        if mode == 'queue':
            threading.Thread(target=self._queue_worker, daemon=True).start()

    def trigger(self, msg, matched_rule):
        pm = self.pass_message.lower()
        if pm == 'keyword':
            arg = matched_rule.split()[0].upper()
        elif pm == 'message':
            arg = msg['content']
        else:
            arg = None
        self._dispatch(arg)

    def trigger_keyword(self, keyword):
        """Triggers the alert script directly with a keyword string."""
        self._dispatch(keyword)

    def _dispatch(self, arg):
        if self.mode == 'interrupt':
            self._interrupt_and_run(arg)
        else:
            if self._queue.full():
                try:
                    self._queue.get_nowait()
                except Empty:
                    pass
            try:
                self._queue.put_nowait(arg)
            except Exception:
                pass

    def _run_script(self, arg):
        cmd = ['python3', self.script]
        if arg:
            cmd.append(arg)
        try:
            self._proc = subprocess.Popen(cmd)
            self._proc.wait(timeout=self.timeout)
        except subprocess.TimeoutExpired:
            self._proc.terminate()
            log_error(self.error_logger, logging.WARNING,
                      f"Alert script exceeded timeout of {self.timeout}s and was terminated")
        except Exception as e:
            log_error(self.error_logger, logging.ERROR, "Alert script failed", e)
        finally:
            self._proc = None

    def _interrupt_and_run(self, arg):
        with self._lock:
            if self._proc and self._proc.poll() is None:
                try:
                    self._proc.send_signal(signal.SIGTERM)
                    time.sleep(2)
                    if self._proc.poll() is None:
                        self._proc.kill()
                except Exception as e:
                    log_error(self.error_logger, logging.WARNING,
                              "Failed to interrupt alert script", e)
            self._thread = threading.Thread(
                target=self._run_script, args=(arg,), daemon=True)
            self._thread.start()

    def _queue_worker(self):
        while True:
            try:
                arg = self._queue.get(timeout=1)
                self._run_script(arg)
            except Empty:
                continue
            except Exception as e:
                log_error(self.error_logger, logging.ERROR,
                          "Alert queue worker error", e)


# ── SMTP ──────────────────────────────────────────────────────────────────────

def smtp_connect(config):
    s = config['smtp']
    if s.get('type', 'ssl').lower() == 'ssl':
        server = smtplib.SMTP_SSL(s['host'], int(s['port']))
    else:
        server = smtplib.SMTP(s['host'], int(s['port']))
        server.ehlo()
        server.starttls()
    server.login(s['user'], s['password'])
    return server


def send_raw_mail(config, smtp_logger, error_logger, subject, body,
                  retry_count=3, retry_delay=30):
    """Sends a mail via SMTP with retry. Logs OK or ERR to smtp log."""
    s         = config['smtp']
    recipient = s['recipient']

    for attempt in range(1, retry_count + 1):
        try:
            msg = MIMEMultipart()
            msg['From']    = s['user']
            msg['To']      = recipient
            msg['Subject'] = subject
            msg.attach(MIMEText(body, 'plain', 'utf-8'))
            with smtp_connect(config) as server:
                server.sendmail(s['user'], recipient, msg.as_string())
            if smtp_logger:
                smtp_logger.info(f"{now()} | OK  | To: {recipient} | Subject: {subject}")
            return True
        except Exception as e:
            if smtp_logger:
                smtp_logger.info(
                    f"{now()} | ERR | Attempt {attempt}/{retry_count} | {e} | Subject: {subject}")
            log_error(error_logger, logging.ERROR,
                      f"SMTP send failed (attempt {attempt}/{retry_count})", e)
            if attempt < retry_count:
                time.sleep(retry_delay)
    return False


def send_test_mail(config, smtp_logger, error_logger):
    print(f"[{now()}] Sending test mail...")
    send_raw_mail(
        config, smtp_logger, error_logger,
        subject     = "OSPAL - Test mail",
        body        = f"{now()}\nThis is a test mail from OSPAL {VERSION}.\nSMTP configuration is working.",
        retry_count = 1,
    )
    print(f"[{now()}] Done - check smtp log for result.")


# ── ntfy ──────────────────────────────────────────────────────────────────────

def send_ntfy(config, ntfy_logger, error_logger, title, message,
              priority='default', retry_count=3, retry_delay=30):
    """Sends a notification via ntfy with retry. Logs OK or ERR to ntfy log."""
    n     = config['ntfy']
    url   = n.get('url', 'https://ntfy.sh').rstrip('/')
    topic = n.get('topic', '')
    token = n.get('token', '').strip()

    if not topic:
        log_error(error_logger, logging.ERROR, "ntfy topic is not configured")
        return False

    ntfy_url = f"{url}/{topic}"
    prio_num = str(NTFY_PRIORITIES.get(priority.lower(), 3))

    for attempt in range(1, retry_count + 1):
        try:
            headers = {
                'Title':        title,
                'Priority':     prio_num,
                'Content-Type': 'text/plain; charset=utf-8',
            }
            if token:
                headers['Authorization'] = f'Bearer {token}'
            req = urllib.request.Request(
                ntfy_url, data=message.encode('utf-8'),
                headers=headers, method='POST'
            )
            urllib.request.urlopen(req, timeout=10).read()
            if ntfy_logger:
                ntfy_logger.info(
                    f"{now()} | OK  | {ntfy_url} | Priority: {priority} | Title: {title}")
            return True
        except Exception as e:
            if ntfy_logger:
                ntfy_logger.info(
                    f"{now()} | ERR | Attempt {attempt}/{retry_count} | {e} | Title: {title}")
            log_error(error_logger, logging.ERROR,
                      f"ntfy send failed (attempt {attempt}/{retry_count})", e)
            if attempt < retry_count:
                time.sleep(retry_delay)
    return False


def send_test_ntfy(config, ntfy_logger, error_logger):
    print(f"[{now()}] Sending test ntfy notification...")
    send_ntfy(
        config, ntfy_logger, error_logger,
        title       = "OSPAL - Test notification",
        message     = f"{now()}\nThis is a test notification from OSPAL {VERSION}.\nntfy configuration is working.",
        priority    = 'default',
        retry_count = 1,
    )
    print(f"[{now()}] Done - check ntfy log for result.")


# ── Formatting ────────────────────────────────────────────────────────────────

def get_uptime():
    delta = datetime.now() - START_TIME
    h, rem = divmod(int(delta.total_seconds()), 3600)
    m, s   = divmod(rem, 60)
    return f"{h}h {m}m {s}s"


def get_errors_exist(log_dir):
    error_log = os.path.join(log_dir, f"{date.today().strftime('%Y-%m-%d')}-error.log")
    if not os.path.exists(error_log):
        return "No errors"
    with open(error_log, encoding='utf-8', errors='replace') as f:
        lines = [l.strip() for l in f if l.strip()]
    if not lines:
        return "No errors"
    counts = {}
    for line in lines:
        m = re.search(r'\[(DEBUG|INFO|WARNING|ERROR|CRITICAL)\]', line)
        if m:
            counts[m.group(1)] = counts.get(m.group(1), 0) + 1
    if counts:
        return f"Errors present: {', '.join(f'{v} {k}' for k, v in counts.items())}"
    return f"{len(lines)} error entries"


def build_variables(config, msg, matched_rule, timestamp, log_dir, priority='default'):
    keyword = matched_rule.split()[0].replace('ADDRESS:', 'Address ').upper()
    return {
        'keyword':         keyword,
        'message':         msg['content'],
        'message_preview': msg['content'][:60].strip(),
        'address':         str(msg['address']),
        'function':        str(msg['function']),
        'timestamp':       timestamp,
        'uptime':          get_uptime(),
        'last_restart':    START_TIME.strftime('%Y-%m-%d %H:%M:%S'),
        'frequency':       config.get('receiver', 'frequency', fallback='?'),
        'errors_exist':    get_errors_exist(log_dir),
        'ospal_version':   VERSION,
        'priority':        priority,
    }


def format_alert_mail(config, msg, matched_rule, timestamp, log_dir, priority='default'):
    fmt         = config['mail_format'] if config.has_section('mail_format') else {}
    subject_tpl = fmt.get('subject', DEFAULT_SUBJECT_TEMPLATE) if fmt else DEFAULT_SUBJECT_TEMPLATE
    body_tpl    = fmt.get('body',    DEFAULT_BODY_TEMPLATE)    if fmt else DEFAULT_BODY_TEMPLATE
    variables   = build_variables(config, msg, matched_rule, timestamp, log_dir, priority)
    return (subject_tpl.format(**variables),
            body_tpl.replace('\\n', '\n').format(**variables))


def format_alert_ntfy(config, msg, matched_rule, timestamp, log_dir, priority='default'):
    ntfy_cfg    = config['ntfy'] if config.has_section('ntfy') else {}
    subject_tpl = ntfy_cfg.get('subject', DEFAULT_SUBJECT_TEMPLATE) if ntfy_cfg else DEFAULT_SUBJECT_TEMPLATE
    body_tpl    = ntfy_cfg.get('body',    DEFAULT_BODY_TEMPLATE)    if ntfy_cfg else DEFAULT_BODY_TEMPLATE
    variables   = build_variables(config, msg, matched_rule, timestamp, log_dir, priority)
    return (subject_tpl.format(**variables),
            body_tpl.replace('\\n', '\n').format(**variables))


# ── Daily log scheduler ───────────────────────────────────────────────────────

def send_daily_log_notifications(config, smtp_logger, ntfy_logger, error_logger,
                                  log_dir, target_date, retry_count=3, retry_delay=30):
    """
    Sends daily log summaries via mail and/or ntfy.
    Each enabled log is sent as a separate message.
    Non-existent logs are reported rather than silently skipped.
    """
    date_str     = target_date.strftime('%Y-%m-%d')
    archive_root = os.path.join(log_dir, 'archive', target_date.strftime('%Y-%m'))
    mail_enabled = config.getboolean('smtp', 'mail_enabled', fallback=False)
    ntfy_enabled = config.getboolean('ntfy', 'ntfy_enabled', fallback=False)

    def get_bool(section, key):
        return config.getboolean(section, key, fallback=False) if config.has_section(section) else False

    for suffix in ['raw', 'filtered', 'keywords', 'smtp', 'ntfy', 'error']:
        send_mail = mail_enabled and get_bool('smtp', f'mail_log_{suffix}')
        send_ntfy_log = ntfy_enabled and get_bool('ntfy', f'ntfy_log_{suffix}')
        if not send_mail and not send_ntfy_log:
            continue

        archive_path = os.path.join(archive_root, f"{date_str}-{suffix}.log")
        current_path = os.path.join(log_dir, f"{date_str}-{suffix}.log")

        if os.path.exists(archive_path):
            log_path = archive_path
        elif os.path.exists(current_path):
            log_path = current_path
        else:
            log_path = None

        subject = f"OSPAL Daily Log - {date_str} - {suffix}"
        if log_path:
            with open(log_path, encoding='utf-8', errors='replace') as f:
                content = f.read().strip()
            body = content if content else f"[{date_str}] Log file exists but contains no entries."
        else:
            body = f"[{date_str}] Log file was not created - no {suffix} events occurred."

        if send_mail:
            send_raw_mail(config, smtp_logger, error_logger, subject, body,
                         retry_count=retry_count, retry_delay=retry_delay)
        if send_ntfy_log:
            send_ntfy(config, ntfy_logger, error_logger, subject, body,
                     retry_count=retry_count, retry_delay=retry_delay)


class DailyLogScheduler:
    """Runs the daily log notification at a configured time. Background thread."""

    def __init__(self, config, smtp_logger, ntfy_logger, error_logger, log_dir,
                 retry_count=3, retry_delay=30):
        self.config       = config
        self.smtp_logger  = smtp_logger
        self.ntfy_logger  = ntfy_logger
        self.error_logger = error_logger
        self.log_dir      = log_dir
        self.retry_count  = retry_count
        self.retry_delay  = retry_delay
        self._last_run    = None

        try:
            h, m = config.get('smtp', 'mail_log_time', fallback='06:00').split(':')
            self.send_hour, self.send_minute = int(h), int(m)
        except ValueError:
            self.send_hour, self.send_minute = 6, 0

        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while True:
            now_dt = datetime.now()
            if (now_dt.hour   == self.send_hour and
                    now_dt.minute == self.send_minute and
                    self._last_run != now_dt.date()):
                try:
                    send_daily_log_notifications(
                        self.config, self.smtp_logger, self.ntfy_logger,
                        self.error_logger, self.log_dir,
                        now_dt.date() - timedelta(days=1),
                        self.retry_count, self.retry_delay
                    )
                    self._last_run = now_dt.date()
                except Exception as e:
                    log_error(self.error_logger, logging.ERROR,
                              "Failed to send daily log notification", e)
            time.sleep(30)


# ── Silent receiver watchdog ──────────────────────────────────────────────────

class SilentReceiverWatchdog:
    """
    Monitors multimon-ng output. If no output is received for silent_minutes,
    sends a warning via mail/ntfy and optionally triggers the alert script
    with OSPAL-SILENT. Repeats up to max_warnings times per silence period.
    Counter resets when activity resumes.
    """

    def __init__(self, config, smtp_logger, ntfy_logger, error_logger,
                 log_dir, alert_runner, retry_count=3, retry_delay=30):
        self.config       = config
        self.smtp_logger  = smtp_logger
        self.ntfy_logger  = ntfy_logger
        self.error_logger = error_logger
        self.log_dir      = log_dir
        self.alert_runner = alert_runner
        self.retry_count  = retry_count
        self.retry_delay  = retry_delay

        sr = config['silent_receiver'] if config.has_section('silent_receiver') else {}

        self.enabled       = sr.getboolean('enabled',       fallback=False) if sr else False
        self.silent_mins   = int(sr.get('silent_minutes',   '12'))          if sr else 12
        self.max_warnings  = int(sr.get('max_warnings',     '2'))           if sr else 2
        self.send_mail     = sr.getboolean('send_mail',     fallback=True)  if sr else True
        self.send_ntfy_w   = sr.getboolean('send_ntfy',     fallback=False) if sr else False
        self.trigger_alert = sr.getboolean('trigger_alert', fallback=True)  if sr else True

        self._last_activity = time.time()
        self._last_warning  = None
        self._warnings_sent = 0
        self._lock          = threading.Lock()

        if self.enabled:
            threading.Thread(target=self._run, daemon=True).start()

    def activity(self):
        """Called each time a line is received from multimon-ng."""
        with self._lock:
            self._last_activity = time.time()
            self._last_warning  = None
            self._warnings_sent = 0

    def _run(self):
        while True:
            time.sleep(60)
            if not self.enabled:
                continue
            with self._lock:
                now_t       = time.time()
                silent_secs = now_t - self._last_activity
                # First warning: triggered after silent_mins of silence
                # Subsequent warnings: each triggered after another silent_mins interval
                if silent_secs >= self.silent_mins * 60 and self._warnings_sent < self.max_warnings:
                    if (self._last_warning is None or
                            now_t - self._last_warning >= self.silent_mins * 60):
                        self._warnings_sent += 1
                        self._last_warning   = now_t
                        self._send_warning(int(silent_secs // 60))

    def _send_warning(self, silent_mins):
        subject = f"OSPAL-SILENT - No output from receiver for {silent_mins} minutes"
        body    = (
            f"{now()}\n"
            f"OSPAL has received no output from multimon-ng for {silent_mins} minutes.\n\n"
            f"Uptime   : {get_uptime()}\n"
            f"Started  : {START_TIME.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Warning  : {self._warnings_sent} of {self.max_warnings}\n"
            f"OSPAL    : v{VERSION}"
        )

        log_error(self.error_logger, logging.WARNING,
                  f"No multimon-ng output for {silent_mins} minutes "
                  f"(warning {self._warnings_sent}/{self.max_warnings})")

        mail_enabled = self.config.getboolean('smtp', 'mail_enabled', fallback=False)
        ntfy_enabled = self.config.getboolean('ntfy', 'ntfy_enabled', fallback=False)

        if self.send_mail and mail_enabled:
            send_raw_mail(self.config, self.smtp_logger, self.error_logger,
                         subject, body,
                         retry_count=self.retry_count,
                         retry_delay=self.retry_delay)

        if self.send_ntfy_w and ntfy_enabled:
            send_ntfy(self.config, self.ntfy_logger, self.error_logger,
                     subject, body, priority='high',
                     retry_count=self.retry_count,
                     retry_delay=self.retry_delay)

        if self.trigger_alert and self.alert_runner:
            self.alert_runner.trigger_keyword(SILENT_RECEIVER_KEYWORD)


# ── Error logging ─────────────────────────────────────────────────────────────

def log_error(error_logger, level, context, exc=None):
    level_name = logging.getLevelName(level)
    if exc:
        message = f"[{now()}] [{level_name}] {context}: {type(exc).__name__}: {exc}"
        tb      = traceback.format_exc()
    else:
        message = f"[{now()}] [{level_name}] {context}"
        tb      = None

    print(message, file=sys.stderr)
    if tb:
        print(tb, file=sys.stderr)

    if error_logger and error_logger.isEnabledFor(level):
        error_logger.log(level, message)
        if tb:
            error_logger.log(level, tb.rstrip())


# ── Calibration ───────────────────────────────────────────────────────────────

def calibrate(config_path, minutes):
    """
    Runs RTL-SDR calibration for specified minutes.
    Detects tuner type, measures PPM, writes results to ospal.ini.
    Uses pty so rtl_test outputs unbuffered.
    """
    import pty
    import select

    if minutes < MIN_CALIBRATION_MINUTES:
        print(f"[OSPAL] NOTE: Recommended minimum is {MIN_CALIBRATION_MINUTES} min - proceeding with {minutes} min.")

    print(f"[OSPAL] Starting PPM calibration for {minutes} minutes...")
    print(f"[OSPAL] Tip: Let dongle warm up 5-10 minutes before calibrating.")
    print(f"[OSPAL] rtl_test running for {minutes} minutes - waiting for readings...")
    print()

    ppm_values = []
    gain = sample_rate = tuner = None
    master_fd, slave_fd = pty.openpty()

    try:
        proc = subprocess.Popen(
            ['rtl_test', '-p'],
            stdin=slave_fd, stdout=slave_fd, stderr=slave_fd, close_fds=True
        )
        os.close(slave_fd)
        start_time = time.time()
        buf = ''

        while True:
            if time.time() - start_time >= minutes * 60:
                proc.terminate()
                break
            ready, _, _ = select.select([master_fd], [], [], 1.0)
            if not ready:
                if proc.poll() is not None:
                    break
                continue
            try:
                buf += os.read(master_fd, 1024).decode('utf-8', errors='replace')
            except OSError:
                break

            while '\n' in buf or '\r' in buf:
                for sep in ['\n', '\r']:
                    if sep in buf:
                        line, buf = buf.split(sep, 1)
                        break
                line = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', line)
                line = re.sub(r'\x1b[^a-zA-Z]*[a-zA-Z]', '', line)
                line = re.sub(r'[\x00-\x09\x0b-\x1f\x7f]', '', line).strip()
                if not line:
                    continue

                if 'tuner' in line.lower() and tuner is None:
                    tuner = line
                    print(f"[OSPAL] Dongle: {line}")
                    if 'R820T' in line or 'R828D' in line:
                        gain, sample_rate = 40.2, 22050
                    elif 'FC0013' in line:
                        gain, sample_rate = 19.7, 22050
                    else:
                        gain, sample_rate = 30.0, 22050
                    print(f"[OSPAL] Recommended gain: {gain} dB")

                if 'cumulative PPM:' in line:
                    try:
                        ppm     = int(line.split('cumulative PPM:')[1].strip())
                        current = int(line.split('current PPM:')[1].split('cumulative')[0].strip())
                        ppm_values.append(ppm)
                        print(f"[OSPAL] Reading {len(ppm_values)}: current {current:+d}, cumulative {ppm:+d}")
                    except (ValueError, IndexError):
                        pass

    except FileNotFoundError:
        print("[ERROR] rtl_test not found. Is rtl-sdr installed?")
        sys.exit(1)
    except KeyboardInterrupt:
        proc.terminate()
        print(f"\n[OSPAL] Calibration interrupted.")
    finally:
        try:
            os.close(master_fd)
        except OSError:
            pass

    if not ppm_values:
        print("[ERROR] No PPM values received. Check dongle connection.")
        sys.exit(1)

    final_ppm = ppm_values[-1]
    spread    = max(ppm_values) - min(ppm_values) if len(ppm_values) > 1 else None

    print()
    if spread is None:
        print(f"[OSPAL] Done! PPM: {final_ppm:+d} (single reading - run longer for reliability)")
    else:
        print(f"[OSPAL] Done! PPM: {final_ppm:+d}, spread: +-{spread//2}")

    if spread is None or spread > PPM_SPREAD_WARNING:
        print(f"[OSPAL] WARNING: Large spread - dongle may be cold. Let warm up ~20 min and retry.")
        print(f"[OSPAL] Value {final_ppm:+d} written to {config_path} but may be unreliable.")
    else:
        print("[OSPAL] Spread acceptable - value is reliable.")

    config = configparser.ConfigParser()
    config.read(config_path, encoding='utf-8')
    config.set('receiver', 'ppm',         str(final_ppm))
    config.set('receiver', 'gain',        str(gain))
    config.set('receiver', 'sample_rate', str(sample_rate))
    with open(config_path, 'w', encoding='utf-8') as f:
        config.write(f)
    print(f"[OSPAL] Wrote PPM={final_ppm}, gain={gain}, sample_rate={sample_rate} to {config_path}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def format_line(timestamp, msg):
    return (
        f"[{timestamp}] {msg['type']}: "
        f"Address: {msg['address']}  "
        f"Function: {msg['function']}  "
        f"{msg['content_type']}: {msg['content']}"
    )


# ── Main loop ─────────────────────────────────────────────────────────────────

def run(config_path='ospal.ini'):
    """Main function - starts RTL-SDR and multimon-ng and processes output."""
    global config_ref

    config     = load_config(config_path)
    config_ref = config
    validate_config(config)

    rcv     = config['receiver']
    filt    = config['filtering']
    log_cfg = config['logging']

    log_dir           = resolve_path(log_cfg.get('log_dir', 'logs'))
    log_level_name    = log_cfg.get('log_level', 'info').lower()
    log_level         = LOG_LEVELS.get(log_level_name, logging.INFO)
    archive_keep_days = int(log_cfg.get('archive_keep_days', 0))

    archive_stale_logs(log_dir, archive_keep_days)

    charset                    = build_charset(config)
    charset_address_blacklist  = get_charset_address_blacklist(config)
    charset_function_blacklist = get_charset_function_blacklist(config)
    address_blacklist          = get_address_blacklist(config)
    keyword_blacklist          = get_keyword_blacklist(config)
    filtering_enabled          = filt.getboolean('enabled', fallback=False)
    decode_format              = rcv.get('decode_format', 'alpha').lower()
    terminal_output            = log_cfg.get('terminal_output', 'raw').lower()

    mail_enabled = config.getboolean('smtp', 'mail_enabled', fallback=False)
    mail_alerts  = config.getboolean('smtp', 'mail_alerts',  fallback=True)
    ntfy_enabled = config.getboolean('ntfy', 'ntfy_enabled', fallback=False)
    ntfy_alerts  = config.getboolean('ntfy', 'ntfy_alerts',  fallback=True)
    retry_count  = int(config.get('smtp', 'retry_count', fallback='3'))
    retry_delay  = int(config.get('smtp', 'retry_delay', fallback='30'))

    dup_enabled = log_cfg.getboolean('duplicate_suppression',    fallback=True)
    dup_window  = int(log_cfg.get('duplicate_window_seconds',    '120'))
    dup_chars   = int(log_cfg.get('duplicate_match_chars',       '32'))
    duplicates  = DuplicateSuppressor(enabled=dup_enabled,
                                      window_seconds=dup_window,
                                      match_chars=dup_chars)

    def log_enabled(key, default=True):
        return log_cfg.getboolean(key, fallback=default)

    raw_logger      = setup_logger('raw',      log_dir, 'raw',      log_level, archive_keep_days) if log_enabled('raw_enabled')                else None
    filtered_logger = setup_logger('filtered', log_dir, 'filtered', log_level, archive_keep_days) if log_enabled('filtered_enabled')           else None
    keywords_logger = setup_logger('keywords', log_dir, 'keywords', log_level, archive_keep_days) if log_enabled('keywords_enabled')           else None
    smtp_logger     = setup_logger('smtp',     log_dir, 'smtp',     log_level, archive_keep_days) if log_enabled('smtp_enabled')               else None
    ntfy_logger     = setup_logger('ntfy',     log_dir, 'ntfy',     log_level, archive_keep_days) if log_enabled('ntfy_log_enabled', False)    else None
    error_logger    = setup_logger('error',    log_dir, 'error',    log_level, archive_keep_days) if log_enabled('error_enabled', False)       else None

    # Alert runner
    alert_runner = None
    if config.has_section('alert') and config.getboolean('alert', 'enabled', fallback=False):
        alert_runner = AlertRunner(
            script       = config.get('alert', 'script'),
            mode         = config.get('alert', 'mode', fallback='interrupt'),
            timeout      = int(config.get('alert', 'timeout', fallback='600')),
            pass_message = config.get('alert', 'pass_message', fallback='message'),
            queue_max    = int(config.get('alert', 'queue_max', fallback='1')),
            error_logger = error_logger,
        )

    # Daily log scheduler - start if any log delivery is configured
    need_scheduler = any([
        mail_enabled and config.getboolean('smtp', k, fallback=False)
        for k in ['mail_log_raw', 'mail_log_filtered', 'mail_log_smtp',
                  'mail_log_ntfy', 'mail_log_error', 'mail_log_keywords']
    ] + [
        ntfy_enabled and config.getboolean('ntfy', k, fallback=False)
        for k in ['ntfy_log_raw', 'ntfy_log_filtered', 'ntfy_log_smtp',
                  'ntfy_log_ntfy', 'ntfy_log_error', 'ntfy_log_keywords']
    ])
    if need_scheduler:
        DailyLogScheduler(config, smtp_logger, ntfy_logger, error_logger,
                         log_dir, retry_count, retry_delay)

    # Silent receiver watchdog
    watchdog = SilentReceiverWatchdog(
        config, smtp_logger, ntfy_logger, error_logger,
        log_dir, alert_runner, retry_count, retry_delay
    )

    # Log startup
    log_error(error_logger, logging.INFO, f"OSPAL {VERSION} started")
    if log_level == logging.DEBUG:
        log_error(error_logger, logging.DEBUG,
                  f"freq={rcv['frequency']} | format={decode_format} | "
                  f"filter={'on' if filtering_enabled else 'off'} | "
                  f"mail={'on' if mail_enabled else 'off'} | "
                  f"mail_alerts={'on' if mail_alerts else 'off'} | "
                  f"ntfy={'on' if ntfy_enabled else 'off'} | "
                  f"ntfy_alerts={'on' if ntfy_alerts else 'off'} | "
                  f"alert_script={'on' if alert_runner else 'off'}")

    print(f"[{now()}] OSPAL {VERSION} starting - listening on {rcv['frequency']} MHz...")
    print(f"[{now()}] Format: {decode_format} | Filter: {'on' if filtering_enabled else 'off'} | "
          f"Mail: {'on' if mail_enabled else 'off'} | ntfy: {'on' if ntfy_enabled else 'off'} | "
          f"Terminal: {terminal_output} | Log level: {log_level_name}")

    if terminal_output == 'raw':
        print(f"[{now()}] TIP: Running headless? Set terminal_output = filtered in ospal.ini once dialled in.")
    if not mail_enabled:
        print(f"[{now()}] NOTE: Mail disabled. Set mail_enabled = true in [smtp] to enable.")
    if not ntfy_enabled:
        print(f"[{now()}] NOTE: ntfy disabled. Set ntfy_enabled = true in [ntfy] to enable.")

    rtl_cmd = [
        'rtl_fm', '-f', rcv['frequency'], '-s', rcv['sample_rate'],
        '-g', rcv['gain'], '-p', rcv['ppm'], '-'
    ]
    multimon_cmd = [
        'multimon-ng', '-t', 'raw',
        '-a', 'POCSAG512', '-a', 'POCSAG1200', '-a', 'POCSAG2400',
        '-f', decode_format, '-'
    ]

    try:
        try:
            rtl_proc = subprocess.Popen(
                rtl_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            multimon_proc = subprocess.Popen(
                multimon_cmd, stdin=rtl_proc.stdout,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding='latin-1'
            )
            rtl_proc.stdout.close()
        except Exception as e:
            log_error(error_logger, logging.CRITICAL,
                      "Failed to start rtl_fm or multimon-ng", e)
            sys.exit(1)

        for line in multimon_proc.stdout:
            try:
                line      = line.rstrip('\n')
                timestamp = now()

                watchdog.activity()

                if raw_logger:
                    raw_logger.info(f"[{timestamp}] {line}")
                if terminal_output == 'raw':
                    print(f"[{timestamp}] {line}")

                msg = parse_pocsag_line(line)
                if not msg:
                    continue

                if (msg['address'] not in charset_address_blacklist and
                        msg['function'] not in charset_function_blacklist):
                    msg['content'] = apply_charset(msg['content'], charset)

                blacklisted = should_blacklist(
                    msg, address_blacklist, keyword_blacklist, filtering_enabled)

                if not blacklisted:
                    filtered_line = format_line(timestamp, msg)
                    if filtered_logger:
                        filtered_logger.info(filtered_line)
                    if terminal_output == 'filtered':
                        print(filtered_line)

                    if msg['content']:
                        matched_rule, rule_key = find_matching_rule(msg, [])
                        if matched_rule:
                            if keywords_logger:
                                keywords_logger.info(filtered_line)
                            if terminal_output == 'keywords':
                                print(filtered_line)

                            if not duplicates.is_duplicate(msg['content']):
                                duplicates.record(msg['content'])

                                priority = get_rule_priority(rule_key, config) if rule_key else 'default'

                                if mail_enabled and mail_alerts:
                                    subject, body = format_alert_mail(
                                        config, msg, matched_rule,
                                        timestamp, log_dir, priority)
                                    send_raw_mail(
                                        config, smtp_logger, error_logger,
                                        subject, body, retry_count, retry_delay)

                                if ntfy_enabled and ntfy_alerts:
                                    title, ntfy_body = format_alert_ntfy(
                                        config, msg, matched_rule,
                                        timestamp, log_dir, priority)
                                    send_ntfy(
                                        config, ntfy_logger, error_logger,
                                        title, ntfy_body, priority,
                                        retry_count, retry_delay)

                                if alert_runner:
                                    alert_runner.trigger(msg, matched_rule)

            except Exception as e:
                log_error(error_logger, logging.ERROR,
                          f"Error processing line: {repr(line)}", e)

    except KeyboardInterrupt:
        print(f"\n[{now()}] OSPAL stopping...")
        log_error(error_logger, logging.INFO, f"OSPAL {VERSION} stopped by user")
    finally:
        log_error(error_logger, logging.INFO,
                  f"OSPAL {VERSION} shutting down | uptime: {get_uptime()}")
        try:
            if 'multimon_proc' in locals():
                multimon_proc.terminate()
        except Exception as e:
            log_error(error_logger, logging.WARNING, "Failed to terminate multimon-ng", e)
        try:
            if 'rtl_proc' in locals():
                rtl_proc.terminate()
        except Exception as e:
            log_error(error_logger, logging.WARNING, "Failed to terminate rtl_fm", e)


# ── Command line ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description=f'OSPAL {VERSION} - Open Source POCSAG Alert Logger')
    parser.add_argument('-t', '--calibrate', metavar='MINUTES', type=int, nargs='?',
                        const=DEFAULT_CALIBRATION_MINUTES,
                        help=f'Calibrate dongle. Default: {DEFAULT_CALIBRATION_MINUTES} min.')
    parser.add_argument('-m', '--testmail', action='store_true',
                        help='Send test mail using current SMTP settings.')
    parser.add_argument('-n', '--testntfy', action='store_true',
                        help='Send test ntfy notification using current ntfy settings.')
    parser.add_argument('-c', '--config', metavar='FILE', default='ospal.ini',
                        help='Config file (default: ospal.ini).')
    args = parser.parse_args()

    if args.calibrate is not None:
        calibrate(args.config, args.calibrate)
    elif args.testmail:
        config       = load_config(args.config)
        validate_config(config)
        log_cfg      = config['logging']
        log_dir      = resolve_path(log_cfg.get('log_dir', 'logs'))
        smtp_logger  = setup_logger('smtp',  log_dir, 'smtp')  if log_cfg.getboolean('smtp_enabled',  fallback=True)  else None
        error_logger = setup_logger('error', log_dir, 'error') if log_cfg.getboolean('error_enabled', fallback=False) else None
        send_test_mail(config, smtp_logger, error_logger)
    elif args.testntfy:
        config       = load_config(args.config)
        validate_config(config)
        log_cfg      = config['logging']
        log_dir      = resolve_path(log_cfg.get('log_dir', 'logs'))
        ntfy_logger  = setup_logger('ntfy',  log_dir, 'ntfy')  if log_cfg.getboolean('ntfy_log_enabled', fallback=True)  else None
        error_logger = setup_logger('error', log_dir, 'error') if log_cfg.getboolean('error_enabled',    fallback=False) else None
        send_test_ntfy(config, ntfy_logger, error_logger)
    else:
        run(args.config)


if __name__ == '__main__':
    main()

# CHANGELOG

All notable changes to OSPAL are documented here.

---

## [0.7.1] - 2026-04-28

### Fixed
- SilentReceiverWatchdog now waits a full silent_minutes interval between
  consecutive warnings instead of just 60 seconds. Previously, warning 2/2
  would fire only one minute after warning 1/2 regardless of the configured
  interval. Now each subsequent warning waits the same duration as the first.
- _last_warning timestamp is reset to None when activity resumes, ensuring
  the interval logic is clean for the next silence period.

---

## [0.7.0] - 2026-04-28

### Added
- ntfy push notification support - works alongside or instead of mail.
  Supports both ntfy.sh (public) and self-hosted instances.
  Configurable via new [ntfy] section in ospal.ini.
- ntfy_log_enabled - separate log file for ntfy events (ntfy.log), lazy like smtp.log.
- ntfy_alerts - separate toggle for individual alert notifications via ntfy.
- Daily log summaries can now also be sent via ntfy (ntfy_log_* keys in [ntfy]).
- ntfy priority per rule - add rule1_priority = high after a rule to set the
  ntfy priority for that specific rule. Available levels: min, low, default, high, max.
- {priority} variable available in both mail and ntfy format templates.
- -n / --testntfy command line flag - sends a test ntfy notification.
- SMTP and ntfy retry on failure - configurable retry_count and retry_delay in [smtp].
  Applies to both individual alert messages and daily log summaries.
- Silent receiver watchdog - configurable warning when no output is received from
  multimon-ng for a set number of minutes. Sends via mail and/or ntfy, and can
  trigger the alert script with the reserved keyword OSPAL-SILENT. Repeats up to
  max_warnings times per silence period. Counter resets on activity.
- [silent_receiver] section in ospal.ini with full configuration.

### Fixed
- Alert script validation no longer checks execute bit - only file existence.
  Scripts called with python3 explicitly do not require the execute bit.
- Startup DEBUG log message no longer contains a double timestamp.
- Startup message now shows mail_alerts and alert_script status separately
  instead of the ambiguous 'alerts=on'.

### Changed
- REQUIRED_CONFIG no longer requires smtp keys unconditionally - smtp keys are
  only required when mail_enabled = true. This allows running OSPAL with only
  ntfy configured.
- find_matching_rule now returns (rule_value, rule_key) tuple to enable priority
  lookup per rule. rule_key is the ini key name e.g. 'rule1'.
- Default retry_count = 3, retry_delay = 30 seconds.

---

## [0.6.2] - 2026-04-09

### Fixed
- DuplicateSuppressor now strips NUL and other control characters from message
  content before comparison. multimon-ng sometimes appends NUL bytes to messages
  which prevented otherwise identical messages from being recognised as duplicates.
- DuplicateSuppressor now cleans history before recording a new entry rather than
  after, preventing a race condition where a freshly recorded entry could be
  immediately purged if the time window was short.
- Log files from previous dates that were not archived due to OSPAL being
  restarted before a rollover was triggered are now moved to the archive
  directory at startup.
- Duplicate _purge_old_archives logic consolidated into a single top-level
  function shared by DailyFileHandler and archive_stale_logs.

### Changed
- Default duplicate_window_seconds changed from 60 to 120.
- Default duplicate_match_chars changed from 48 to 32.

---

## [0.6.1] - 2026-04-08

### Fixed
- Placeholder file creation for empty logs removed from doRollover. Logs that
  were never created are simply not archived.
- Inline comments on boolean values in ospal.ini removed. Python configparser
  does not support inline comments on boolean values and would raise ValueError.

### Changed
- keywords_enabled comment updated to clarify that the log is written regardless
  of whether mail is enabled.
- Log archiving comment in ospal.ini corrected to reflect actual behaviour.

---

## [0.6.0] - 2026-04-07

### Added
- keywords.log - new log file containing all messages that matched a mail rule,
  regardless of whether mail was sent or duplicate suppression was active.
- terminal_output = keywords - new option showing only rule-matched messages
  in the terminal.
- DuplicateSuppressor - replaces simple last-message comparison with a
  configurable time window and substring matching.
- Alert script runner with two modes: interrupt (SIGTERM + restart) and queue
  (serial with configurable queue depth).
- pass_message option for alert scripts: none, keyword or message.
- Alert script validated at startup.
- Daily log summary mails - each enabled log mailed separately at a configured time.
- mail_alerts setting - separates individual alert mails from daily log mails.
- Configurable alert mail format with variables.
- {errors_exist} and {ospal_version} mail format variables.
- archive_keep_days setting.
- Log archiving at midnight rollover to logs/archive/YYYY-MM/.
- All log files are now lazy.
- Start, stop and restart events logged to error log.
- duplicate_suppression on/off toggle.
- duplicate_match_chars setting.

### Changed
- Default decode_format changed from auto to alpha.

---

## [0.5.0] - 2026-04-03

### Added
- validate_config() - checks all required ini keys at startup.
- Error log with configurable log level.
- log_error() helper with level parameter.
- DuplicateSuppressor (basic).
- mail_enabled = false as global master switch, false by default.
- mail_alerts setting.
- terminal_output = filtered option.
- resolve_path() - relative paths resolved from script directory.

### Changed
- All log files use lazy initialisation.
- install-service in ospal-ctl.sh now writes correct WorkingDirectory.

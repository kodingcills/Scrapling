#!/bin/bash
# Cron wrapper for the scheduled lead_engine `targets` run.
#
# Cron's environment is minimal: no interactive-shell PATH, no pyenv, no
# nvm. Every path here is absolute on purpose. Output is appended to a
# date-stamped log file so there is a paper trail beyond the email summary.
#
# macOS note: cron jobs silently fail to access files if /usr/sbin/cron
# lacks Full Disk Access (System Settings > Privacy & Security > Full Disk
# Access). If a scheduled run produces no log file and no email, grant
# that first - it is a permissions problem, not a code bug.
#
# Schedule (see scripts/README.md): Sunday 21:00 local time, weekly. That
# cadence is a default chosen because Findymail credits are finite - tune
# it once the real credit burn rate is known.

set -u

LEAD_ENGINE_DIR="/Users/tofuinparis/Projects/Scrapling/lead_engine"
UV_BIN="/Users/tofuinparis/.local/bin/uv"
LOG_DIR="${LEAD_ENGINE_DIR}/logs"

mkdir -p "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/targets_$(date +%Y%m%d).log"

cd "${LEAD_ENGINE_DIR}" || exit 1

{
    echo "=== targets run starting $(date -u '+%Y-%m-%dT%H:%M:%SZ') ==="
    "${UV_BIN}" run python main.py targets data/target_companies.yaml
    status=$?
    echo "=== targets run finished $(date -u '+%Y-%m-%dT%H:%M:%SZ') exit=${status} ==="
} >> "${LOG_FILE}" 2>&1

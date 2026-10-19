#!/bin/sh
# Idempotently install the language runtimes our coding problems need into
# Piston.
#
# Why this exists: Piston starts with an EMPTY package store. The runtimes live
# in the `piston_data` volume, so a fresh volume (first boot, `compose down -v`,
# volume prune, VM rebuild) leaves Piston running but with zero languages. In
# that state every /api/v2/execute call fails, coding/services.py raises
# EngineError and the API returns 503 on every Run/Submit -- while `docker
# compose ps` still shows piston as "Up". This script closes that gap by
# re-provisioning on every `compose up`.
#
# Idempotency: already-installed packages are skipped (probed via
# /api/v2/runtimes); a racing re-install is tolerated because Piston answers
# "Already installed" for those.
#
# Keep PACKAGES in sync with backend/coding/languages.py.
set -eu

PISTON_URL="${PISTON_URL:-http://piston:2000}"
# install_language:install_version:probe_language:probe_version
#
# The probe pair is not always the install pair: installing `gcc` registers the
# c / c++ / d / fortran runtimes, so we probe for the c++ runtime we actually use.
PACKAGES="python:3.12.0:python:3.12.0
java:15.0.2:java:15.0.2
gcc:10.2.0:c++:10.2.0"

log() { echo "[piston-init] $*"; }

# Piston needs a moment to bind :2000 and load its package index.
log "waiting for Piston at ${PISTON_URL} ..."
i=0
until curl -sf -o /dev/null "${PISTON_URL}/api/v2/runtimes"; do
  i=$((i + 1))
  if [ "$i" -ge 60 ]; then
    log "ERROR: Piston did not become reachable after 60 attempts"
    exit 1
  fi
  sleep 5
done
log "Piston is reachable"

runtimes="$(curl -sf "${PISTON_URL}/api/v2/runtimes" || echo '[]')"

echo "$PACKAGES" | while IFS=: read -r lang ver probe_lang probe_ver; do
  [ -n "$lang" ] || continue

  if echo "$runtimes" | grep -q "\"language\":\"${probe_lang}\",\"version\":\"${probe_ver}\""; then
    log "ok: ${probe_lang} ${probe_ver} already installed"
    continue
  fi

  log "installing ${lang} ${ver} (this can take several minutes) ..."
  # --max-time 0 disables the transfer cap: gcc is a large download.
  body="$(curl -s --max-time 0 -w '\n%{http_code}' \
    -H 'Content-Type: application/json' \
    -d "{\"language\":\"${lang}\",\"version\":\"${ver}\"}" \
    "${PISTON_URL}/api/v2/packages" || echo "\n000")"
  code="$(echo "$body" | tail -n1)"
  msg="$(echo "$body" | sed '$d')"

  case "$code" in
    200)
      log "installed ${lang} ${ver}"
      ;;
    *)
      # A concurrent/duplicate install answers 500 "Already installed" -- benign.
      if echo "$msg" | grep -q 'Already installed'; then
        log "ok: ${lang} ${ver} already installed"
      else
        log "ERROR: failed to install ${lang} ${ver} (HTTP ${code}): ${msg}"
      fi
      ;;
  esac
done

# Re-read the runtime list so the exit status reflects reality rather than the
# individual install calls (the loop above runs in a subshell in POSIX sh, so
# state cannot escape it).
final="$(curl -sf "${PISTON_URL}/api/v2/runtimes" || echo '[]')"
echo "$PACKAGES" | while IFS=: read -r lang ver probe_lang probe_ver; do
  [ -n "$lang" ] || continue
  echo "$final" | grep -q "\"language\":\"${probe_lang}\",\"version\":\"${probe_ver}\"" \
    || echo "$probe_lang $probe_ver"
done > /tmp/missing.txt
missing="$(cat /tmp/missing.txt)"

if [ -n "$missing" ]; then
  log "ERROR: runtimes still missing after provisioning:"
  echo "$missing" | while read -r m; do log "  - $m"; done
  exit 1
fi

log "all required runtimes present"
exit 0

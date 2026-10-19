#!/usr/bin/env bash
# Acceptance test for scripts/mirror-image-dir.sh and its use in deploy-vps.sh.
#
# WHY: `cp -a` in the theme refresh never deletes, so two team photos removed from
# the repo in #140 survived the deploy. The mirror must remove files the image no
# longer has WITHOUT ever touching operator data under /app/data. This test drives
# both halves: removals happen inside the mirrored scope, and uploads outside it
# (and the /app/data root itself) are never touched.
#
# Run locally: bash scripts/test-mirror-image-dir.sh   (no docker, no network)
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MIRROR="${REPO_ROOT}/scripts/mirror-image-dir.sh"
DEPLOY="${REPO_ROOT}/scripts/deploy-vps.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

pass=0
fail=0
ok() { echo "  PASS  $1"; pass=$((pass + 1)); }
bad() { echo "  FAIL  $1"; fail=$((fail + 1)); }
expect() { # expect <name> <command...>
    local name="$1"; shift
    if "$@"; then ok "${name}"; else bad "${name}"; fi
}
gone() { [ ! -e "$1" ] && [ ! -L "$1" ]; }
has() { [ -e "$1" ]; }
text() { [ "$(cat "$1")" = "$2" ]; }

SRC="${TMP}/image/themes"
DST="${TMP}/data/themes"
mkdir -p "${SRC}/intent_learn/team" "${SRC}/keep" "${TMP}/data/files/public" "${DST}/intent_learn/team" "${DST}/removed_theme/img" "${DST}/keep"
echo new > "${SRC}/intent_learn/team/max.jpeg"
echo v2 > "${SRC}/keep/style.css"
ln -s style.css "${SRC}/keep/link.css"
echo old > "${DST}/intent_learn/team/max.jpeg"
echo gone1 > "${DST}/intent_learn/team/opeyemi.jpeg"
echo gone2 > "${DST}/intent_learn/team/tolulope.jpeg"
echo v1 > "${DST}/keep/style.css"
echo stale > "${DST}/keep/stale-link-target"
ln -s stale-link-target "${DST}/keep/stale-link"
echo gone3 > "${DST}/removed_theme/img/x.png"
echo upload > "${TMP}/data/files/public/member-upload.pdf"

echo "== mirror: additions, overwrites, deletions =="
sh "${MIRROR}" "${SRC}" "${DST}"; rc=$?
expect "exits 0"                          [ "${rc}" = 0 ]
expect "new content overwrites stale"     text "${DST}/keep/style.css" v2
expect "kept file refreshed"              text "${DST}/intent_learn/team/max.jpeg" new
expect "removed photo 1 is gone"          gone "${DST}/intent_learn/team/opeyemi.jpeg"
expect "removed photo 2 is gone"          gone "${DST}/intent_learn/team/tolulope.jpeg"
expect "removed stale symlink is gone"    gone "${DST}/keep/stale-link"
expect "removed theme directory is gone"  gone "${DST}/removed_theme"
expect "image symlink is copied"          has "${DST}/keep/link.css"
expect "upload outside scope untouched"   text "${TMP}/data/files/public/member-upload.pdf" upload

echo "== mirror is idempotent =="
sh "${MIRROR}" "${SRC}" "${DST}"; rc=$?
expect "second run exits 0"               [ "${rc}" = 0 ]
expect "second run keeps content"         text "${DST}/keep/style.css" v2

echo "== mirror refuses unsafe calls =="
EMPTY="${TMP}/empty"; mkdir -p "${EMPTY}"
sh "${MIRROR}" "${EMPTY}" "${DST}" 2>/dev/null; rc=$?
expect "empty source refused"             [ "${rc}" = 2 ]
expect "empty source left DST alone"      has "${DST}/keep/style.css"
for protected in /app/data /app / /app/now_lms/static; do
    sh "${MIRROR}" "${SRC}" "${protected}" 2>/dev/null; rc=$?
    expect "protected destination ${protected} refused" [ "${rc}" = 2 ]
done
sh "${MIRROR}" "${TMP}/nope" "${DST}" 2>/dev/null; rc=$?
expect "missing source refused"           [ "${rc}" = 2 ]
sh "${MIRROR}" onlyone 2>/dev/null; rc=$?
expect "wrong argument count refused"     [ "${rc}" = 2 ]

echo "== deploy-vps.sh scope (static check) =="
calls="$(grep -c 'sh /app/scripts/mirror-image-dir.sh' "${DEPLOY}")"
expect "exactly two mirror calls"         [ "${calls}" = 2 ]
expect "templates mirrored into /app/themes" grep -q 'mirror-image-dir.sh /app/now_lms/templates /app/themes$' "${DEPLOY}"
expect "static themes mirrored into /app/data/themes" grep -q 'mirror-image-dir.sh /app/now_lms/static/themes /app/data/themes$' "${DEPLOY}"
expect "/app/data root is merged, never mirrored" grep -q 'cp -a /app/now_lms/static/. /app/data/$' "${DEPLOY}"
if grep -nE 'mirror-image-dir.sh [^ ]+ /app/data/?$|rsync|--delete' "${DEPLOY}" >/dev/null; then
    bad "deploy-vps.sh never mirrors /app/data root or uses rsync/--delete"
else
    ok "deploy-vps.sh never mirrors /app/data root or uses rsync/--delete"
fi

echo
echo "passed=${pass} failed=${fail}"
[ "${fail}" -eq 0 ]

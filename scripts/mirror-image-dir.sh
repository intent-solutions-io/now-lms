#!/bin/sh
# Make DST an exact mirror of SRC: copy everything in, then remove whatever DST
# holds that SRC no longer has. Used by deploy-vps.sh to refresh the volume-shadowed
# theme directories from the image (fork issue: two team photos deleted in #140
# survived the deploy because `cp -a` only ever adds and overwrites).
#
# Runs INSIDE the app container (POSIX sh, no rsync there). SCOPE IS THE CALLER'S
# JOB: pass only directories the image owns outright. Never pass /app/data, which
# also holds operator uploads (files/public and friends); this script refuses it.
#
# Usage: mirror-image-dir.sh SRC DST
# Exit:  0 mirrored, 2 refused (bad arguments, empty SRC, protected DST)
set -eu

if [ "$#" -ne 2 ]; then
    echo "usage: mirror-image-dir.sh SRC DST" >&2
    exit 2
fi
src="${1%/}"
dst="${2%/}"

[ -d "${src}" ] || { echo "mirror: source is not a directory: ${src}" >&2; exit 2; }
# An empty source would turn the delete pass into "wipe the destination".
if [ -z "$(ls -A "${src}")" ]; then
    echo "mirror: refusing, source is empty: ${src}" >&2
    exit 2
fi
case "${dst}" in
    "" | / | /app | /app/data | /app/now_lms | /app/now_lms/static | /app/now_lms/templates | /data)
        echo "mirror: refusing protected destination: ${dst:-/}" >&2
        exit 2
        ;;
esac

mkdir -p "${dst}"
cp -a "${src}/." "${dst}/"

# Files and symlinks present in DST but not in SRC.
(cd "${dst}" && find . -mindepth 1 ! -type d -print) | while IFS= read -r p; do
    if [ ! -e "${src}/${p}" ] && [ ! -L "${src}/${p}" ]; then
        rm -f -- "${dst}/${p}"
    fi
done
# Directories absent from SRC, deepest first (their files are already gone).
(cd "${dst}" && find . -mindepth 1 -depth -type d -print) | while IFS= read -r p; do
    [ -d "${src}/${p}" ] || rmdir -- "${dst}/${p}"
done

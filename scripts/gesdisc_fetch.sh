#!/bin/bash
# Fetch a large Earthdata-protected file in parallel range chunks.
#
# WHY: GES DISC throttles each connection to about 45 KB/s sustained.  A
# single curl of a 408 MB MERRA-2 day therefore takes roughly 2.5 hours.  The
# throttle is per connection, not per account: four concurrent range requests
# measured 332 KB/s aggregate, about 7x.  Range requests are honoured
# (Content-Range comes back on a plain GET), so the file can be fetched as
# independent chunks and concatenated.
#
# Usage: gesdisc_fetch.sh URL OUTPUT [CHUNKS]
#
# The token is read from ~/.earthdata_token and is never echoed.

set -u

URL="$1"
OUT="$2"
CHUNKS="${3:-16}"
TOKEN_FILE="${EARTHDATA_TOKEN_FILE:-$HOME/.earthdata_token}"

if [ ! -r "$TOKEN_FILE" ]; then
  echo "no token at $TOKEN_FILE" >&2
  exit 2
fi
TOKEN=$(tr -d '\n' < "$TOKEN_FILE")

# Total size, from a one-byte range request.
# Content-Range is "Content-Range: bytes 0-0/408491562", so the total is the
# part after the slash in the THIRD whitespace-separated field.  Reading $2
# yields the literal "bytes" and silently produces an empty size.
TOTAL=$(curl -sS -m 60 -H "Authorization: Bearer $TOKEN" -r 0-0 -D- -o /dev/null "$URL" 2>/dev/null \
        | tr -d '\r' | awk 'tolower($1)=="content-range:"{n=split($3,a,"/"); print a[n]}')
case "$TOTAL" in
  ''|*[!0-9]*) echo "could not determine size (check the URL and the token)" >&2; exit 3 ;;
esac
echo "total $TOTAL bytes, $CHUNKS chunks"

TMP=$(mktemp -d "${TMPDIR:-/tmp}/gesdisc.XXXXXX")
trap 'rm -rf "$TMP"' EXIT

STEP=$(( (TOTAL + CHUNKS - 1) / CHUNKS ))
pids=""
for i in $(seq 0 $((CHUNKS - 1))); do
  a=$(( i * STEP ))
  [ "$a" -ge "$TOTAL" ] && break
  b=$(( a + STEP - 1 ))
  [ "$b" -ge "$TOTAL" ] && b=$(( TOTAL - 1 ))
  (
    curl -sS -m 3600 --retry 4 --retry-delay 3 --retry-all-errors \
         -H "Authorization: Bearer $TOKEN" -r "$a-$b" -o "$TMP/part.$i" "$URL" \
      || echo "chunk $i failed" >> "$TMP/failures"
  ) &
  pids="$pids $!"
done
wait $pids

if [ -s "$TMP/failures" ]; then
  echo "some chunks failed:" >&2
  cat "$TMP/failures" >&2
  exit 4
fi

: > "$OUT"
i=0
while [ -e "$TMP/part.$i" ]; do
  cat "$TMP/part.$i" >> "$OUT"
  i=$((i + 1))
done

GOT=$(stat -f '%z' "$OUT" 2>/dev/null || stat -c '%s' "$OUT")
if [ "$GOT" != "$TOTAL" ]; then
  echo "size mismatch: got $GOT, expected $TOTAL" >&2
  exit 5
fi
echo "ok $OUT $GOT bytes"

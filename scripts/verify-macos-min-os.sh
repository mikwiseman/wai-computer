#!/usr/bin/env bash
#
# verify-macos-min-os.sh — guards against the CATap dyld launch-crash class.
#
# WaiComputer ships one (universal) binary with a macOS deployment floor below 14.2,
# but uses Core Audio Process Taps (CATap: CATapDescription,
# AudioHardwareCreateProcessTap) which are macOS 14.2+. Those symbols MUST be
# weak-linked (-weak_framework CoreAudio AudioToolbox) or dyld aborts at launch on
# macOS 13.0–14.1 — before any `if #available` runs. Neither `swift test` nor
# `xcodebuild build` catches this; only inspecting the built Mach-O does. Every
# shipped architecture slice is checked. Wire this into the release pipeline.
#
# Usage: verify-macos-min-os.sh <path/to/WaiComputer.app> [expected_minos]
set -euo pipefail

APP="${1:?usage: verify-macos-min-os.sh <WaiComputer.app> [expected_minos]}"
EXPECT_MINOS="${2:-13.0}"
MAIN="$APP/Contents/MacOS/WaiComputer"
[ -f "$MAIN" ] || { echo "FAIL: executable not found at $MAIN"; exit 1; }

# The CATap-using code is in the main executable (Release) or in
# WaiComputer.debug.dylib (Debug builds use a debug-dylib stub).
TARGET=""
for b in "$MAIN" "$APP/Contents/MacOS/WaiComputer.debug.dylib"; do
  [ -f "$b" ] || continue
  syms=$(nm -m "$b" 2>/dev/null || true)
  if [[ "$syms" == *AudioHardwareCreateProcessTap* ]]; then TARGET="$b"; break; fi
done
[ -n "$TARGET" ] || { echo "FAIL: no binary references AudioHardwareCreateProcessTap — system-audio code missing?"; exit 1; }
echo "Inspecting: ${TARGET##*/}"

ARCHS=$(lipo -archs "$TARGET" 2>/dev/null || true)
[ -n "$ARCHS" ] || ARCHS=$(uname -m)
echo "Architectures: $ARCHS"

fail=0

# Deployment floor must match on every slice of the main executable.
minos_bad=$(vtool -show-build "$MAIN" | awk '/minos/{print $2}' | grep -vx "$EXPECT_MINOS" || true)
if [ -z "$minos_bad" ]; then
  echo "OK: minos=$EXPECT_MINOS (all slices)"
else
  echo "FAIL: unexpected minos value(s): $(vtool -show-build "$MAIN" | awk '/minos/{print $2}' | tr '\n' ' ')(expected $EXPECT_MINOS)"
  fail=1
fi

for a in $ARCHS; do
  for fw in CoreAudio AudioToolbox; do
    kind=$(otool -arch "$a" -l "$TARGET" 2>/dev/null | awk '/^[[:space:]]*cmd LC_LOAD/{c=$2} /^[[:space:]]*name /{ if ($2 ~ "/'"$fw"'\\.framework/") {print c; exit} }')
    if [ "$kind" = "LC_LOAD_WEAK_DYLIB" ]; then
      echo "OK[$a]: $fw weak-linked"
    else
      echo "FAIL[$a]: $fw is '${kind:-not linked}', expected LC_LOAD_WEAK_DYLIB"
      fail=1
    fi
  done
  # Every 14.2 CATap symbol that dyld must bind (undefined) must be weak — a bare
  # '(undefined) external' would abort launch on macOS <14.2. Local defined metadata
  # symbols ('non-external', e.g. ...CML/...Ma) are in-binary and never bound — ignore.
  strong=$(nm -m -arch "$a" "$TARGET" 2>/dev/null | grep -iE "CATapDescription|AudioHardware(Create|Destroy)ProcessTap" | grep "(undefined)" | grep -v "weak" || true)
  if [ -z "$strong" ]; then
    echo "OK[$a]: all CATap 14.2 symbols weak/absent"
  else
    echo "FAIL[$a]: strongly-linked CATap symbol(s) — would crash on macOS <14.2:"
    echo "$strong"
    fail=1
  fi
done

if [ "$fail" -eq 0 ]; then echo "PASS: $APP is safe to launch on macOS $EXPECT_MINOS+"; else echo "FAILED min-OS verification"; fi
exit $fail

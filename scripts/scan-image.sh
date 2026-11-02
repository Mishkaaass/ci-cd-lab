#!/bin/sh
set -eu

if [ "$#" -ne 1 ] || [ -z "$1" ]; then
    printf 'Usage: sh scripts/scan-image.sh IMAGE\n' >&2
    exit 2
fi
image="$1"

scan() {
    trivy image --scanners vuln --pkg-types os,library --no-progress \
        "$@" "$image"
}

printf 'Report: all HIGH and CRITICAL findings, including unfixed\n'
scan --severity HIGH,CRITICAL --ignore-unfixed=false --exit-code 0

printf 'Gate: all CRITICAL findings block release\n'
scan --severity CRITICAL --ignore-unfixed=false --exit-code 1

printf 'Gate: HIGH findings with an available fix block release\n'
scan --severity HIGH --ignore-unfixed=true --exit-code 1

printf 'PASS: container security policy; review unfixed HIGH findings above\n'

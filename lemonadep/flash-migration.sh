#!/usr/bin/env bash
# Flash lemonadep 6.18 migration images to the inactive A/B slot.
# The script intentionally waits for fastboot transitions so it can be started
# before putting a flaky bootloader into fastboot mode.

set -euo pipefail

SLOT=${SLOT:-a}
IMAGE_DIR=${1:-}
TIMEOUT=${FASTBOOT_TIMEOUT:-4}

usage() {
    cat <<EOF2
usage: SLOT=a $0 /path/to/dist/migration

Environment:
  SLOT       target inactive slot (default: a)
  YES=1      skip the interactive confirmation prompt
  REBOOT=0   stop after set-active instead of rebooting into the test
EOF2
}

die() {
    echo "error: $*" >&2
    exit 1
}

log() {
    printf '\n==> %s\n' "$*"
}

[ -n "$IMAGE_DIR" ] || { usage >&2; exit 2; }
IMAGE_DIR=$(cd "$IMAGE_DIR" && pwd)
for img in boot.img vendor_boot.img dtbo.img vendor_dlkm.img; do
    [ -f "$IMAGE_DIR/$img" ] || die "missing $IMAGE_DIR/$img"
done
command -v fastboot >/dev/null || die "fastboot is not in PATH"
command -v timeout >/dev/null || die "timeout is not in PATH"
[ "$SLOT" = a ] || [ "$SLOT" = b ] || die "SLOT must be a or b"

fb_capture() {
    timeout "$TIMEOUT" fastboot "$@" 2>&1 || true
}

fb_must() {
    log "fastboot $*"
    timeout "$TIMEOUT" fastboot "$@" 2>&1
}

getvar() {
    local var=$1 out
    out=$(fb_capture getvar "$var")
    printf '%s\n' "$out" | tr -d '\r' | sed -n "s/.*${var}: \(.*\)/\1/p" | head -n1
}

raw_getvar_output() {
    fb_capture getvar "$1"
}

is_userspace() {
    getvar is-userspace
}

wait_for_fastboot() {
    local mode
    log "waiting for a fastboot device"
    while :; do
        mode=$(is_userspace)
        if [ "$mode" = yes ] || [ "$mode" = no ]; then
            echo "fastboot connected: is-userspace=$mode"
            return 0
        fi
        printf '.'
        sleep 0.2
    done
}

wait_for_mode() {
    local want=$1 mode tries=0
    log "waiting for fastboot mode is-userspace=$want"
    while :; do
        mode=$(is_userspace)
        if [ "$mode" = "$want" ]; then
            echo "mode reached: is-userspace=$mode"
            return 0
        fi
        tries=$((tries + 1))
        if [ "$tries" -gt 300 ]; then
            die "timed out waiting for is-userspace=$want (last value: ${mode:-none})"
        fi
        printf '.'
        sleep 0.2
    done
}

partition_size_bytes() {
    local part=$1 value
    value=$(getvar "partition-size:$part")
    case "$value" in
        0x[0-9a-fA-F]*)
            printf '%d\n' "$((16#${value#0x}))"
            ;;
        ''|*[!0-9]*)
            printf '0\n'
            ;;
        *)
            printf '%d\n' "$value"
            ;;
    esac
}

cat <<EOF2
This will overwrite boot, vendor_boot, dtbo and vendor_dlkm on slot $SLOT.
The currently running slot must remain the fallback. Do not continue unless
slot $SLOT is inactive and its crDroid logical partitions already exist.
EOF2

if [ "${YES:-0}" != 1 ]; then
    read -r -p "Type FLASH-SLOT-$SLOT to continue: " answer
    [ "$answer" = "FLASH-SLOT-$SLOT" ] || die "confirmation did not match"
fi

LOG_FILE=$IMAGE_DIR/flash-slot-${SLOT}-$(date +%Y%m%d-%H%M%S).log
# shellcheck disable=SC2094
exec > >(tee "$LOG_FILE") 2>&1

cd "$IMAGE_DIR"
log "image directory: $IMAGE_DIR"
sha256sum boot.img vendor_boot.img dtbo.img vendor_dlkm.img

wait_for_fastboot
mode=$(is_userspace)
current=$(getvar current-slot)
echo "current-slot: ${current:-unknown}; target slot: $SLOT"
if [ "$current" = "$SLOT" ]; then
    die "target slot $SLOT is currently active; refusing to flash the running system"
fi

if [ "$mode" != yes ]; then
    fb_must reboot fastboot
    wait_for_mode yes
fi

snapshot=$(getvar snapshot-update-status)
echo "snapshot-update-status: ${snapshot:-unknown}"
if [ -n "$snapshot" ] && [ "$snapshot" != none ]; then
    die "a Virtual A/B merge is pending; boot the working slot and let it finish first"
fi

log "checking logical partitions for slot $SLOT"
missing=()
for base in system system_ext product vendor odm; do
    part=${base}_${SLOT}
    logical=$(getvar "is-logical:$part")
    size=$(getvar "partition-size:$part")
    echo "$part: is-logical=${logical:-unknown} size=${size:-unknown}"
    [ "$logical" = yes ] || missing+=("$part")
done
if ((${#missing[@]})); then
    die "inactive slot is missing required logical partitions: ${missing[*]}; no partition was written"
fi

vendor_dlkm=vendor_dlkm_${SLOT}
need_size=$(stat -c %s vendor_dlkm.img)
logical=$(getvar "is-logical:$vendor_dlkm")
echo "$vendor_dlkm: is-logical=${logical:-unknown} required-size=$need_size"
if [ "$logical" = yes ]; then
    have_size=$(partition_size_bytes "$vendor_dlkm")
    echo "$vendor_dlkm: current-size=$have_size"
    if [ "$have_size" -lt "$need_size" ]; then
        fb_must resize-logical-partition "$vendor_dlkm" "$need_size"
    fi
else
    fb_must create-logical-partition "$vendor_dlkm" "$need_size"
fi

fb_must flash "$vendor_dlkm" vendor_dlkm.img
fb_must reboot bootloader
wait_for_mode no

fb_must flash "boot_${SLOT}" boot.img
fb_must flash "vendor_boot_${SLOT}" vendor_boot.img
fb_must flash "dtbo_${SLOT}" dtbo.img
fb_must --set-active="$SLOT"

if [ "${REBOOT:-1}" != 0 ]; then
    fb_must reboot
fi

log "done; log saved to $LOG_FILE"

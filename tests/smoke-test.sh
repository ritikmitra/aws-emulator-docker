#!/usr/bin/env bash
#
# Smoke test for an aws-emulator image.
#
# Starts the image in the background, waits until it's healthy, then checks
# that the AWS CLI reaches the emulator (not real AWS) and that S3 works.
# Always stops the container at the end, even when a check fails.
#
# Usage:   tests/smoke-test.sh [image]
# Example: tests/smoke-test.sh aws-emulator-local
#
# Exit code: 0 if every check passed, non-zero otherwise.

# Stop at the first failing command (-e), treat unset variables as errors (-u),
# and make a pipeline fail if any command in it fails (pipefail).
set -euo pipefail

IMAGE="${1:-aws-emulator-local}"
PORT="${PORT:-9297}"
CONTAINER="aws-emulator-smoke-$$"   # $$ is this script's process ID, so names never clash
BUCKET="smoke-test-bucket-$$"

# A private scratch folder, so the test never touches the real ~/.aws/emulator.
WORKDIR="$(mktemp -d)"
EMU_DIR="$WORKDIR/.aws/emulator/$PORT"
mkdir -p "$WORKDIR/.aws/emulator"

# On Linux (like GitHub Actions), the container must run as correct user ID so it can
# write to the mounted folder. On macOS, Docker Desktop handles this, so keep UID 1000.
if [ "$(uname -s)" = "Linux" ]; then
  RUN_AS="$(id -u):$(id -g)"
else
  RUN_AS="1000:1000"
fi

log()  { echo "==> $*"; }
fail() { echo "FAIL: $*" >&2; exit 1; }

# Runs when the script exits for any reason: success, a failed check, or Ctrl+C.
cleanup() {
  local status=$?
  # Only print logs if the container was actually created.
  if [ "$status" -ne 0 ] && docker container inspect "$CONTAINER" >/dev/null 2>&1; then
    echo "---- emulator logs ----" >&2
    docker logs "$CONTAINER" >&2 2>&1 || true
    echo "-----------------------" >&2
  fi
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  rm -rf "$WORKDIR"
  # Always end with one clear verdict line.
  if [ "$status" -eq 0 ]; then
    echo "PASS: all smoke tests passed"
  else
    echo "FAIL: smoke test failed (exit code $status)" >&2
  fi
  exit "$status"
}
trap cleanup EXIT

log "Image: $IMAGE"
docker run --rm "$IMAGE" -v

log "Starting the emulator on 127.0.0.1:$PORT"
# No --rm here on purpose: if the emulator crashes, its logs survive for cleanup() to print.
docker run -d --name "$CONTAINER" \
  --user "$RUN_AS" \
  --memory=2g --memory-swap=2g \
  -p "127.0.0.1:${PORT}:${PORT}" \
  -e HOME="$WORKDIR" \
  -v "$WORKDIR/.aws/emulator:$WORKDIR/.aws/emulator" \
  "$IMAGE" -p "$PORT" --telemetry off >/dev/null

log "Waiting for the health check (up to 30 seconds)"
for i in $(seq 30); do
  if curl -sf --cacert "$EMU_DIR/ca.pem" "https://127.0.0.1:${PORT}/__admin/health" >/dev/null 2>&1; then
    log "Healthy after ${i}s"
    break
  fi
  if [ "$i" -eq 30 ]; then
    fail "the emulator wasn't healthy after 30 seconds"
  fi
  sleep 1
done

# Point the AWS CLI at the emulator. These exports only affect this script.
export AWS_ENDPOINT_URL="https://127.0.0.1:${PORT}"
export AWS_SHARED_CREDENTIALS_FILE="$EMU_DIR/emulator_credentials"
export AWS_CONFIG_FILE="$EMU_DIR/config"
export AWS_CA_BUNDLE="$EMU_DIR/ca.pem"
export AWS_EC2_METADATA_DISABLED=true
export AWS_DISABLE_HOST_PREFIX_INJECTION=true
export AWS_REGION=us-east-1
export AWS_DEFAULT_REGION=us-east-1
export AWS_PAGER=""   # stop the AWS CLI from opening a pager, which would hang a script
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_PROFILE

log "Safety check: are we talking to the emulator?"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
[ "$ACCOUNT" = "000000000000" ] || fail "expected account 000000000000, got '$ACCOUNT'. Requests may be going to real AWS."

log "S3: create a bucket"
aws s3api create-bucket --bucket "$BUCKET" >/dev/null

log "S3: upload and download an object"
EXPECTED="hello from smoke test $$"
printf '%s' "$EXPECTED" > "$WORKDIR/hello.txt"
aws s3 cp "$WORKDIR/hello.txt" "s3://$BUCKET/hello.txt" >/dev/null
ACTUAL="$(aws s3 cp "s3://$BUCKET/hello.txt" -)"
[ "$ACTUAL" = "$EXPECTED" ] || fail "downloaded '$ACTUAL', expected '$EXPECTED'"
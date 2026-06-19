#!/bin/bash
# Reusable driver: run a local script on every node over IAP, one at a time.
#   bash tasks/run-on-all.sh <remote-script.sh>
# Does NOT source wg-ssh-lib.sh (keeps real gcloud so --tunnel-through-iap applies).
set -u
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
source config.sh
REMOTE="${1:?usage: run-on-all.sh <remote-script>}"
for i in "${!INSTANCE_NAMES[@]}"; do
  echo "================ ${INSTANCE_NAMES[$i]} (${ZONES[$i]}) ================"
  gcloud compute ssh "${INSTANCE_NAMES[$i]}" --zone="${ZONES[$i]}" --project=tn-devnet \
    --tunnel-through-iap --quiet --ssh-flag="-o ConnectTimeout=20" \
    --command='bash -s' < "$REMOTE" 2>&1 \
    | grep -vE 'NumPy|increase the (performance|TCP)|cloud\.google\.com/iap|^WARNING: *$'
  echo ""
done

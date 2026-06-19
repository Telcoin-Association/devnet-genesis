#!/bin/bash
# Local driver: loop all nodes (bash array semantics) and pipe the read-only
# assessment over IAP. Run from anywhere: `bash tasks/phase1-assess.sh`.
set -u
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
source config.sh   # arrays + CLOUDSDK_CORE_PROJECT=tn-devnet; we do NOT source wg-ssh-lib.sh
for i in "${!INSTANCE_NAMES[@]}"; do
  echo "================ ${INSTANCE_NAMES[$i]} (${ZONES[$i]}) ================"
  gcloud compute ssh "${INSTANCE_NAMES[$i]}" --zone="${ZONES[$i]}" --project=tn-devnet \
    --tunnel-through-iap --quiet --ssh-flag="-o ConnectTimeout=20" \
    --command='bash -s' < tasks/assess.sh 2>&1 \
    | grep -vE 'NumPy|increase the (performance|TCP)|cloud\.google\.com/iap|^WARNING: *$|^$'
  echo ""
done

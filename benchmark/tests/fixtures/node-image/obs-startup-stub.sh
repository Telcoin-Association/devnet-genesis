#!/bin/bash
# Stand-in for common/observability/obs-vm/startup-obs.sh (test_node_image.py: BENCH_OBS_STARTUP_SCRIPT),
# so the suite needs no `common` checkout: only its path reaches `gcloud compute instances create
# --metadata-from-file`; the stub gcloud never runs it.
echo "[obs-startup] $(date -u) done"

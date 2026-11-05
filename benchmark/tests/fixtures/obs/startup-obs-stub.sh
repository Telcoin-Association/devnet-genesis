#!/bin/bash
# Stand-in for common/observability/obs-vm/startup-obs.sh (test_obs.py): only its path reaches
# `gcloud compute instances create --metadata-from-file`; the fake never runs it.
echo "[obs-startup] $(date -u) done"

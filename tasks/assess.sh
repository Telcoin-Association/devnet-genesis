#!/bin/bash
# Read-only per-node disk assessment (Phase 1). Piped to each node via
# `gcloud compute ssh ... --command='bash -s' < tasks/assess.sh`.
echo "--- df / ---"
df -h /
printf "sudo: "; sudo -n true 2>/dev/null && echo ok || echo "NEEDS-PASSWORD"
echo "--- telcoin data dirs (top) ---"
sudo du -sh /home/validator/telcoin/* 2>/dev/null | sort -rh
echo "--- consensus-db breakdown (kad?) ---"
sudo du -sh /home/validator/telcoin/consensus-db/* 2>/dev/null | sort -rh
echo "--- docker system df ---"
sudo docker system df
echo "--- container json logs (top 5) ---"
sudo sh -c 'du -sh /var/lib/docker/containers/*/*-json.log 2>/dev/null | sort -rh | head -5'
echo "--- reth file-logs dir ---"
sudo du -sh /home/validator/telcoin/logs 2>/dev/null || echo "(no logs dir)"
echo "--- telcoin LogConfig ---"
sudo docker inspect -f '{{json .HostConfig.LogConfig}}' telcoin 2>/dev/null || echo "(no telcoin container)"
echo "--- running containers ---"
sudo docker ps --format '{{.Names}}  {{.Image}}  {{.Status}}'
echo "--- OBS token ---"
curl -sf -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/attributes/OBS_INGEST_TOKEN >/dev/null \
  && echo "TOKEN SET -> logging should be bounded" || echo "NO TOKEN -> logs UNBOUNDED (culprit)"

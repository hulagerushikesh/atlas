#!/usr/bin/env bash
# One-time Google Cloud setup for the Drive connector (E3, T33). Safe to re-run.
#
#   1. lets the Cloud Run service read the two Drive secrets
#   2. creates the account Cloud Scheduler signs its calls as
#   3. creates the 5-minute job that calls POST /connectors/drive/tick
#
# The secrets themselves (atlas-drive-client-secret, atlas-drive-token-key) are
# created by hand without being shown; see docs/deploy.md "Google Drive".
# Usage: scripts/setup_drive_gcp.sh
set -euo pipefail

PROJECT="${PROJECT:-atlas-rag-rush}"
REGION="${REGION:-asia-south1}"
SERVICE="${SERVICE:-atlas-api}"
PUBLIC_URL="${DRIVE_PUBLIC_URL:-https://atlas.hulage.in}"
TICK_SA="atlas-drive-tick@${PROJECT}.iam.gserviceaccount.com"

RUN_SA="$(gcloud projects describe "${PROJECT}" --format 'value(projectNumber)')-compute@developer.gserviceaccount.com"
for s in atlas-drive-client-secret atlas-drive-token-key; do
  echo "→ ${s}: readable by the service"
  gcloud secrets add-iam-policy-binding "${s}" --project "${PROJECT}" \
    --member "serviceAccount:${RUN_SA}" --role roles/secretmanager.secretAccessor \
    --quiet >/dev/null
done

if ! gcloud iam service-accounts describe "${TICK_SA}" --project "${PROJECT}" >/dev/null 2>&1; then
  echo "→ creating ${TICK_SA}"
  gcloud iam service-accounts create atlas-drive-tick --project "${PROJECT}" \
    --display-name "Atlas Drive 5-minute sync (Cloud Scheduler)"
fi

URL="$(gcloud run services describe "${SERVICE}" --project "${PROJECT}" --region "${REGION}" \
  --format 'value(status.url)')"
# The audience must equal DRIVE_PUBLIC_URL: the route checks it.
FLAGS=(--location "${REGION}" --project "${PROJECT}" --schedule "*/5 * * * *"
       --uri "${URL}/connectors/drive/tick" --http-method POST
       --oidc-service-account-email "${TICK_SA}" --oidc-token-audience "${PUBLIC_URL}"
       --attempt-deadline 120s)
if gcloud scheduler jobs describe atlas-drive-tick --location "${REGION}" \
     --project "${PROJECT}" >/dev/null 2>&1; then
  echo "→ updating the atlas-drive-tick job"
  gcloud scheduler jobs update http atlas-drive-tick "${FLAGS[@]}" --quiet >/dev/null
else
  echo "→ creating the atlas-drive-tick job (every 5 minutes)"
  gcloud scheduler jobs create http atlas-drive-tick "${FLAGS[@]}" --quiet >/dev/null
fi
echo "done: secrets readable, scheduler account and job in place"

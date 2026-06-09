#!/usr/bin/env bash
# Full deploy: bootstrap (once) → docker build/push → terraform dev apply
set -euo pipefail

export PATH="$PATH:/Users/anoo4413/Documents/Learning/GCP/google-cloud-sdk/bin"

PROJECT_ID="gen-lang-client-0300667287"
REGION="us-central1"
REPO="letting-copilot"
SERVICE="letting-copilot"
TAG="${1:-$(git rev-parse --short HEAD 2>/dev/null || echo latest)}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/${SERVICE}:${TAG}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "════════════════════════════════════════"
echo " LettingCopilot — Deploy"
echo " Project : ${PROJECT_ID}"
echo " Region  : ${REGION}"
echo " Tag     : ${TAG}"
echo " Image   : ${IMAGE}"
echo "════════════════════════════════════════"

# ── Step 1: Bootstrap (idempotent — creates GCS bucket + Artifact Registry) ──
echo ""
echo "▶ Step 1/4: Bootstrap (GCS state bucket + Artifact Registry)"
cd "${ROOT}/terraform/bootstrap"
terraform init -input=false
terraform apply -auto-approve -input=false
echo "  Bootstrap complete."

# ── Step 2: Docker build & push ───────────────────────────────────────────────
echo ""
echo "▶ Step 2/4: Docker build & push"
cd "${ROOT}"
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet
docker build \
  -t "${IMAGE}" \
  -t "${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/${SERVICE}:latest" .
docker push "${IMAGE}"
docker push "${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/${SERVICE}:latest"
echo "  Image pushed: ${IMAGE}"

# ── Step 3: Terraform dev (Cloud Run + IAM + Secrets, remote state on GCS) ───
echo ""
echo "▶ Step 3/4: Terraform dev — Cloud Run deploy"
cd "${ROOT}/terraform/dev"
terraform init -input=false -reconfigure
terraform apply -auto-approve -input=false -var="image_tag=${TAG}"
echo "  Terraform apply complete."

# ── Step 4: Smoke test ────────────────────────────────────────────────────────
echo ""
echo "▶ Step 4/4: Smoke test"
URL=$(terraform output -raw service_url)
sleep 5
HEALTH=$(curl -sf "${URL}/health" || echo "FAILED")
echo "  Health: ${HEALTH}"

echo ""
echo "════════════════════════════════════════"
echo " ✓ Deployed!"
echo " URL: ${URL}"
echo "════════════════════════════════════════"

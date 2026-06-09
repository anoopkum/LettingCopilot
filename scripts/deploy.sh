#!/usr/bin/env bash
# Quick local deploy script for POC — builds, pushes, and deploys to Cloud Run
set -euo pipefail

PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-letting-copilot-dev}"
REGION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
REPO="letting-copilot"
SERVICE="letting-copilot"
TAG="${1:-$(git rev-parse --short HEAD 2>/dev/null || echo latest)}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/${SERVICE}:${TAG}"

echo "=> Project  : ${PROJECT_ID}"
echo "=> Region   : ${REGION}"
echo "=> Image    : ${IMAGE}"
echo ""

# Auth check
gcloud config set project "${PROJECT_ID}"

# Ensure Artifact Registry repo exists
gcloud artifacts repositories describe "${REPO}" \
  --location="${REGION}" &>/dev/null || \
  gcloud artifacts repositories create "${REPO}" \
    --repository-format=docker \
    --location="${REGION}" \
    --description="LettingCopilot images"

# Configure Docker
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

# Build and push
echo "=> Building Docker image..."
docker build -t "${IMAGE}" .
docker push "${IMAGE}"

# Deploy Terraform
echo "=> Applying Terraform (dev)..."
cd "$(dirname "$0")/../terraform/dev"

if [ ! -f terraform.tfvars ]; then
  cat > terraform.tfvars <<EOF
project_id = "${PROJECT_ID}"
region     = "${REGION}"
image_tag  = "${TAG}"
EOF
else
  # Update image_tag
  sed -i.bak "s/image_tag.*/image_tag = \"${TAG}\"/" terraform.tfvars && rm -f terraform.tfvars.bak
fi

terraform init -upgrade -input=false
terraform apply -auto-approve -input=false

# Get URL
URL=$(gcloud run services describe "${SERVICE}" \
  --region="${REGION}" --format='value(status.url)' 2>/dev/null || echo "")

if [ -n "${URL}" ]; then
  echo ""
  echo "=> Deployed! Service URL: ${URL}"
  echo "=> Health check..."
  sleep 3
  curl -sf "${URL}/health" && echo "" || echo "Health check failed — check logs"
fi

#!/bin/bash
# ==============================================================================
# Script Name: deploy.sh
# Description:
#   Deploys the lightweight serverless Cloud Function for Gemini Enterprise Analytics
#   and schedules it to run nightly at midnight via Cloud Scheduler.
#
# Usage:
#   ./deploy.sh
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARENT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Load .env
if [ -f "$PARENT_DIR/.env" ]; then
  echo "🔍 Loading environment variables from .env..."
  set -a
  source "$PARENT_DIR/.env"
  set +a
elif [ -f .env ]; then
  echo "🔍 Loading environment variables from .env..."
  set -a
  source .env
  set +a
else
  echo "❌ Error: .env file not found."
  exit 1
fi

FUNCTION_NAME="ge-analytics-nightly-sync"
REGION="${BQ_LOCATION:-us-central1}"
# Cloud Functions 2nd gen prefers lower-case regions (e.g. us-central1)
if [ "$REGION" = "US" ] || [ "$REGION" = "us" ]; then
  REGION="us-central1"
elif [ "$REGION" = "EU" ] || [ "$REGION" = "eu" ]; then
  REGION="europe-west1"
fi

SCHEDULER_JOB_NAME="ge-analytics-nightly-trigger"
CRON_SCHEDULE="0 0 * * *" # Every night at midnight UTC

echo "=============================================================================="
echo "🚀 DEPLOYING LIGHTWEIGHT SERVERLESS ANALYTICS SYNC"
echo "=============================================================================="
echo "Project:      $PROJECT_ID"
echo "Dataset:      $DATASET_ID"
echo "Engine ID:    $ENGINE_ID"
echo "Function:     $FUNCTION_NAME ($REGION)"
echo "Schedule:     $CRON_SCHEDULE (Cloud Scheduler: $SCHEDULER_JOB_NAME)"
echo "=============================================================================="

# Enable required APIs non-interactively
echo "Checking required Google Cloud APIs..."
gcloud services enable \
  cloudfunctions.googleapis.com \
  cloudscheduler.googleapis.com \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  --project="$PROJECT_ID" --quiet

# Grant Cloud Build permissions to default service account
PROJECT_NUM=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
SERVICE_ACCOUNT="${PROJECT_NUM}-compute@developer.gserviceaccount.com"

echo "Granting Cloud Build permissions to: ${SERVICE_ACCOUNT}..."
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/cloudbuild.builds.builder" \
  --condition=None --quiet >/dev/null 2>&1 || true

# 1. Deploy Cloud Function (2nd Gen)
echo ""
echo "🚀 [1/2] Deploying Cloud Function '$FUNCTION_NAME'..."
gcloud functions deploy "$FUNCTION_NAME" \
  --gen2 \
  --runtime="python311" \
  --region="$REGION" \
  --source="$SCRIPT_DIR" \
  --entry-point="sync_metrics" \
  --trigger-http \
  --no-allow-unauthenticated \
  --set-env-vars="PROJECT_ID=${PROJECT_ID},ENGINE_ID=${ENGINE_ID},DATASET_ID=${DATASET_ID},GE_LOCATION=${GE_LOCATION:-global}" \
  --project="$PROJECT_ID" \
  --memory=512MB \
  --timeout=300s \
  --quiet

FUNCTION_URL=$(gcloud functions describe "$FUNCTION_NAME" --gen2 --region="$REGION" --project="$PROJECT_ID" --format='value(serviceConfig.uri)')
echo "✅ Function deployed successfully: $FUNCTION_URL"

# 2. Configure Cloud Scheduler Job
echo ""
echo "🚀 [2/2] Configuring Cloud Scheduler Job '$SCHEDULER_JOB_NAME'..."

# Get or use default App Engine / Compute service account for invocation
SERVICE_ACCOUNT=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"-compute@developer.gserviceaccount.com"

# Grant the service account permissions to invoke the function
gcloud functions add-invoker-policy-binding "$FUNCTION_NAME" \
  --region="$REGION" \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --project="$PROJECT_ID" 2>/dev/null || true

# Check if scheduler job exists and create or update
if gcloud scheduler jobs describe "$SCHEDULER_JOB_NAME" --location="$REGION" --project="$PROJECT_ID" >/dev/null 2>&1; then
  echo "ℹ️ Updating existing Cloud Scheduler job..."
  gcloud scheduler jobs update http "$SCHEDULER_JOB_NAME" \
    --location="$REGION" \
    --schedule="$CRON_SCHEDULE" \
    --uri="$FUNCTION_URL" \
    --http-method="POST" \
    --oidc-service-account-email="$SERVICE_ACCOUNT" \
    --oidc-token-audience="$FUNCTION_URL" \
    --project="$PROJECT_ID"
else
  echo "Creating new Cloud Scheduler job..."
  gcloud scheduler jobs create http "$SCHEDULER_JOB_NAME" \
    --location="$REGION" \
    --schedule="$CRON_SCHEDULE" \
    --uri="$FUNCTION_URL" \
    --http-method="POST" \
    --oidc-service-account-email="$SERVICE_ACCOUNT" \
    --oidc-token-audience="$FUNCTION_URL" \
    --project="$PROJECT_ID"
fi

echo ""
echo "=============================================================================="
echo "🎉 DEPLOYMENT COMPLETE!"
echo "Your analytics sync is now scheduled to run automatically every night at 00:00 UTC."
echo "You can manually trigger a test execution anytime with:"
echo "  gcloud scheduler jobs run $SCHEDULER_JOB_NAME --location=$REGION --project=$PROJECT_ID"
echo "=============================================================================="

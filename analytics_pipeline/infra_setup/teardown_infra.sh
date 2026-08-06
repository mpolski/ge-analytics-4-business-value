#!/bin/bash
# ==============================================================================
# Script Name: teardown_infra.sh
# Description:
#   Clean-up and teardown script for Gemini Enterprise Analytics.
#   Safely removes all provisioned cloud infrastructure:
#     1. Cloud Logging Sinks (gemini_agent_creators, gemini_usage_activity_sink)
#     2. BigQuery Views (vw_unified_metrics, vw_user_feature_adoption, vw_feature_adoption_summary, vw_agent_creators)
#     3. BigQuery Dataset and all constituent tables
#     4. Local staging/temporary files
#
# Usage:
#   ./infra_setup/teardown_infra.sh          # Interactive mode (asks confirmation)
#   ./infra_setup/teardown_infra.sh --force  # Non-interactive mode
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARENT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# ------------------------------------------------------------------------------
# Section 1: Load Environment & Validation
# ------------------------------------------------------------------------------
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

if [ -z "$PROJECT_ID" ]; then
  echo "❌ Error: PROJECT_ID is not set in .env file."
  exit 1
fi

if [ -z "$DATASET_ID" ]; then
  echo "❌ Error: DATASET_ID is not set in .env file."
  exit 1
fi

SINK_NAME=${SINK_NAME:-gemini_agent_creators}
USAGE_SINK_NAME=${USAGE_SINK_NAME:-gemini_usage_activity_sink}

echo "=============================================================================="
echo "⚠️  GEMINI ENTERPRISE ANALYTICS - INFRASTRUCTURE TEARDOWN"
echo "=============================================================================="
echo "Project ID:  $PROJECT_ID"
echo "Dataset ID:  $DATASET_ID"
echo "Sinks:       $SINK_NAME, $USAGE_SINK_NAME"
echo "=============================================================================="
echo ""

# Safety Confirmation
if [ "$1" != "--force" ] && [ "$1" != "-f" ]; then
  read -p "⚠️  Are you sure you want to PERMANENTLY DELETE all dataset tables, views, and logging sinks in '$PROJECT_ID'? (y/N): " CONFIRM
  if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
    echo "🛑 Teardown aborted by user. No resources were deleted."
    exit 0
  fi
  echo ""
fi

echo "🚀 Starting resource teardown..."
echo ""

# ------------------------------------------------------------------------------
# Section 2: Delete Cloud Logging Sinks
# ------------------------------------------------------------------------------
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🗑️  [1/3] Removing Cloud Logging Sinks..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Sink 1: Agent Creators Sink
if gcloud logging sinks describe "${SINK_NAME}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud logging sinks delete "${SINK_NAME}" --project="${PROJECT_ID}" --quiet
  echo "  ✅ [Deleted] Cloud Logging Sink: ${SINK_NAME}"
else
  echo "  ℹ️ [Not Found] Cloud Logging Sink '${SINK_NAME}' does not exist (already removed)."
fi

# Sink 2: Usage Activity Sink
if gcloud logging sinks describe "${USAGE_SINK_NAME}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud logging sinks delete "${USAGE_SINK_NAME}" --project="${PROJECT_ID}" --quiet
  echo "  ✅ [Deleted] Cloud Logging Sink: ${USAGE_SINK_NAME}"
else
  echo "  ℹ️ [Not Found] Cloud Logging Sink '${USAGE_SINK_NAME}' does not exist (already removed)."
fi

echo ""

# ------------------------------------------------------------------------------
# Section 3: Delete BigQuery Views & Dataset
# ------------------------------------------------------------------------------
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🗑️  [2/3] Removing BigQuery Dataset, Tables, and Views..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if bq show "${PROJECT_ID}:${DATASET_ID}" >/dev/null 2>&1; then
  echo "  🔍 Found BigQuery dataset '${PROJECT_ID}:${DATASET_ID}'."
  
  # Recursively delete dataset with all tables and views (-r -f -d)
  bq rm -r -f -d "${PROJECT_ID}:${DATASET_ID}"
  echo "  ✅ [Deleted] BigQuery Views: vw_unified_metrics, vw_user_feature_adoption, vw_feature_adoption_summary, vw_agent_creators"
  echo "  ✅ [Deleted] BigQuery Tables: agent_names, historical_creators, agent_session_metrics, discoveryengine_...user_activity, cloudaudit_...data_access"
  echo "  ✅ [Deleted] BigQuery Dataset: ${PROJECT_ID}:${DATASET_ID}"
else
  echo "  ℹ️ [Not Found] BigQuery dataset '${PROJECT_ID}:${DATASET_ID}' does not exist (already removed)."
fi

echo ""

# ------------------------------------------------------------------------------
# Section 4: Clean Local Temporary Files
# ------------------------------------------------------------------------------
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🧹 [3/3] Cleaning Local Temporary Staging Files..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

rm -f /tmp/raw_creator_logs_*.json /tmp/historical_creators_*.jsonl \
      /tmp/raw_user_activity_*.json /tmp/historical_user_activity_*.jsonl \
      /tmp/agent_names_*.jsonl /tmp/ge_sync_stage.*.log 2>/dev/null || true

echo "  ✅ [Cleaned] Temporary local staging logs and JSONL files removed."
echo ""

echo "=============================================================================="
echo "🎉 TEARDOWN COMPLETE! All analytics resources have been successfully removed."
echo "=============================================================================="

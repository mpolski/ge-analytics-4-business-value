#!/bin/bash
# ==============================================================================
# Script Name: sync_data.sh
# Directory:   analytics_pipeline/data_pipelines/
#
# Overview:
#   Lightweight, fast incremental data synchronization script for Gemini
#   Enterprise (GE) Analytics. Refreshes live agent metadata, reconciles
#   display names, and triggers session metrics exports without re-scanning
#   historical Cloud Logging buckets.
#
# When to Use:
#   - Run on-demand whenever new agents, connectors, or data stores are added
#     and you want BigQuery tables updated immediately (without waiting for the
#     nightly `ge-analytics-nightly-sync` Cloud Function).
#   - Run after upgrading repository code or adding new metadata columns (e.g.,
#     `connector_types`, `datastore_names`) to refresh `<DATASET_ID>.agent_names`
#     in ~20 seconds.
#   - Do NOT need to run `initial_data_sync.sh` if real-time Cloud Logging sinks
#     are already active; use this script instead.
#
# What This Script Does (3 Sequential Steps):
#   1. [Step 1/3] Fetch Live Agent Metadata (`fetch_agent_names.py`):
#      - Queries the Discovery Engine API across all configured engines (`ENGINE_ID`).
#      - Automatically migrates `<DATASET_ID>.agent_names` schema if new columns
#        were introduced, and refreshes all agent configurations, system prompts,
#        connected tools (`connector_ids`, `connector_types`), and data stores.
#
#   2. [Step 2/3] Reconcile Display Names from BigQuery Activity Logs:
#      - Executes a SQL `MERGE` from `<DATASET_ID>.discoveryengine_googleapis_com_gemini_enterprise_user_activity`
#        into `<DATASET_ID>.agent_names` to backfill human-readable names for any
#        deleted or runtime-only agents seen in chat telemetry.
#
#   3. [Step 3/3] Export Discovery Engine Session Metrics (`metrics_to_bq.py`):
#      - Invokes the Discovery Engine `analytics:exportMetrics` REST API for each
#        configured engine to export daily session counts and Monthly Active Users
#        (MAU) into `<DATASET_ID>.agent_session_metrics`.
#
# Environment Variables (loaded from `analytics_pipeline/.env`):
#   - PROJECT_ID     (Required) : Target Google Cloud Project ID.
#   - ENGINE_ID      (Required) : Comma-separated engine IDs or "ALL".
#   - DATASET_ID     (Required) : Target BigQuery Dataset name (e.g., `ge_metrics`).
#   - GE_LOCATION    (Optional) : Discovery Engine API region (`global`, `us`, `eu`).
#   - BQ_LOCATION    (Optional) : BigQuery Dataset multi-region (`US` or `EU`).
#
# Prerequisites:
#   - `gcloud` SDK and `bq` CLI installed and authenticated.
#   - Python 3 environment with required packages (`requests`, `google-auth`, `python-dotenv`).
#
# Usage:
#   cd analytics_pipeline
#   ./data_pipelines/sync_data.sh
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

if [ -z "$PROJECT_ID" ]; then
  echo "❌ Error: PROJECT_ID is not set. Please define PROJECT_ID in .env file."
  exit 1
fi

if [ -z "$ENGINE_ID" ]; then
  echo "❌ Error: ENGINE_ID is not set. Please define ENGINE_ID in .env file."
  exit 1
fi

if [ -z "$DATASET_ID" ]; then
  echo "❌ Error: DATASET_ID is not set. Please define DATASET_ID in .env file."
  exit 1
fi

if [ -f "$PARENT_DIR/.venv/bin/python" ]; then
  PYTHON_EXEC="$PARENT_DIR/.venv/bin/python"
elif [ -f "$PARENT_DIR/../.venv/bin/python" ]; then
  PYTHON_EXEC="$PARENT_DIR/../.venv/bin/python"
elif command -v uv >/dev/null 2>&1; then
  PYTHON_EXEC="uv run python"
else
  PYTHON_EXEC="python3"
fi

echo "=============================================================================="
echo "🚀 Running Periodic Gemini Enterprise Analytics Sync"
echo "Project: $PROJECT_ID | Dataset: $DATASET_ID"
echo "=============================================================================="

# 1. Fetch live agent metadata
echo ""
echo "🚀 [1/3] Fetching live agent metadata from Vertex AI API..."
( cd "$PARENT_DIR" && $PYTHON_EXEC data_pipelines/fetch_agent_names.py )

# 2. Reconcile display names from BigQuery user activity logs
echo ""
echo "🚀 [2/3] Synchronizing agent names from audit logs in BigQuery..."
bq query --use_legacy_sql=false "
MERGE INTO \`${PROJECT_ID}.${DATASET_ID}.agent_names\` T
USING (
  SELECT DISTINCT
    COALESCE(
      JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.request.agentsSpec.agentSpecs[0].agentId'),
      JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.request.agentsspec.agentspecs[0].agentid')
    ) AS agent_id,
    COALESCE(
      JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.response.agentInfo.displayName'),
      JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.response.agentinfo.displayname')
    ) AS display_name,
    'Agent Designer' AS agent_type
  FROM \`${PROJECT_ID}.${DATASET_ID}.discoveryengine_googleapis_com_gemini_enterprise_user_activity\`
  WHERE COALESCE(
      JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.response.agentInfo.displayName'),
      JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.response.agentinfo.displayname')
    ) IS NOT NULL
    AND COALESCE(
      JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.request.agentsSpec.agentSpecs[0].agentId'),
      JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.request.agentsspec.agentspecs[0].agentid')
    ) IS NOT NULL
    AND COALESCE(
      JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.request.agentsSpec.agentSpecs[0].agentId'),
      JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.request.agentsspec.agentspecs[0].agentid')
    ) NOT IN ('workflow_summary_agent', 'default_assistant')
) S
ON T.agent_id = S.agent_id
WHEN MATCHED AND (T.display_name IS NULL OR T.display_name = '' OR T.display_name = 'My Agent' OR T.display_name = 'Unknown Name') THEN
  UPDATE SET T.display_name = S.display_name, T.agent_type = S.agent_type
WHEN NOT MATCHED THEN
  INSERT (agent_id, display_name, agent_type)
  VALUES (S.agent_id, S.display_name, S.agent_type);
"
echo "✅ Agent names synchronized."

# 3. Trigger Discovery Engine session metrics export
echo ""
echo "🚀 [3/3] Exporting session metrics to BigQuery..."
( cd "$PARENT_DIR" && $PYTHON_EXEC data_pipelines/metrics_to_bq.py )

echo ""
echo "🎉 Periodic data synchronization complete!"

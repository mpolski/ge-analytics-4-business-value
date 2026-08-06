#!/bin/bash
# ==============================================================================
# Script Name: sync_data.sh
# Description:
#   Periodic / Nightly sync script for Gemini Enterprise Analytics.
#   Performs:
#     1. Live agent metadata sync from Vertex AI API (fetch_agent_names.py)
#     2. Display name synchronization from real-time BigQuery audit logs
#     3. Discovery Engine session metrics export to BigQuery (metrics_to_bq.py)
#
# Requirements:
#   - Python 3 with dependencies installed.
#   - gcloud and bq CLI authenticated.
#   - .env file in analytics_pipeline/ with PROJECT_ID, ENGINE_ID, and DATASET_ID.
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
    JSON_VALUE(jsonPayload, '$.request.agentsSpec.agentSpecs[0].agentId') AS agent_id,
    JSON_VALUE(jsonPayload, '$.response.agentInfo.displayName') AS display_name,
    'Agent Designer' AS agent_type
  FROM \`${PROJECT_ID}.${DATASET_ID}.discoveryengine_googleapis_com_gemini_enterprise_user_activity\`
  WHERE JSON_VALUE(jsonPayload, '$.response.agentInfo.displayName') IS NOT NULL
    AND JSON_VALUE(jsonPayload, '$.request.agentsSpec.agentSpecs[0].agentId') IS NOT NULL
    AND JSON_VALUE(jsonPayload, '$.request.agentsSpec.agentSpecs[0].agentId') NOT IN ('workflow_summary_agent', 'default_assistant')
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

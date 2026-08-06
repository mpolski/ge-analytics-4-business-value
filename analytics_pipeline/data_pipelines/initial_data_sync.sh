#!/bin/bash
# ==============================================================================
# Script Name: initial_data_sync.sh
# Description:
#   One-stop initial data ingestion & backfill pipeline for Gemini Enterprise Analytics.
#   Executes all 4 stages in sequence with live progress animations:
#     Stage 1: Fetch Live Agent Metadata from API (fetch_agent_names.py)
#     Stage 2: Backfill Historical Creators (365 days) from Cloud Audit Logs
#     Stage 3: Backfill Historical User Activity (365 days) from Cloud Logging
#     Stage 4: Synchronize Agent Directory & Export Session Metrics (metrics_to_bq.py)
#
# Requirements:
#   - jq utility installed.
#   - gcloud SDK and bq CLI authenticated.
#   - Python 3 with requirements installed.
#   - .env file with PROJECT_ID, ENGINE_ID, and DATASET_ID.
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARENT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# ------------------------------------------------------------------------------
# Section 1: Pre-flight Checks & Validation
# ------------------------------------------------------------------------------
echo "=============================================================================="
echo "🌟 Gemini Enterprise Analytics - Initial Data Ingestion & Backfill"
echo "=============================================================================="

# 1. Check for jq
if ! command -v jq >/dev/null 2>&1; then
  echo ""
  echo "❌ Error: 'jq' command-line JSON processor is not installed on this machine."
  echo "Please install jq to continue:"
  echo "  - Debian/Ubuntu: sudo apt-get update && sudo apt-get install -y jq"
  echo "  - macOS: brew install jq"
  echo "  - RedHat/CentOS: sudo yum install -y jq"
  exit 1
fi

# 2. Load .env
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
  echo "❌ Error: .env file not found. Please create .env in analytics_pipeline/ from .env_template."
  exit 1
fi

# 3. Verify required variables
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

# 4. Resolve Python executable (virtualenv or uv or system python)
if [ -f "$PARENT_DIR/.venv/bin/python" ]; then
  PYTHON_EXEC="$PARENT_DIR/.venv/bin/python"
elif [ -f "$PARENT_DIR/../.venv/bin/python" ]; then
  PYTHON_EXEC="$PARENT_DIR/../.venv/bin/python"
elif command -v uv >/dev/null 2>&1; then
  PYTHON_EXEC="uv run python"
else
  PYTHON_EXEC="python3"
fi

echo "Project ID:   $PROJECT_ID"
echo "Engine ID:    $ENGINE_ID"
echo "Dataset ID:   $DATASET_ID"
echo "Python Exec:  $PYTHON_EXEC"
echo "=============================================================================="

# 5. Check IAM Permissions
echo "🔍 [Pre-flight] Verifying Google Cloud IAM permissions for project '$PROJECT_ID'..."

REQUIRED_PERMS=(
  "serviceusage.services.use"
  "discoveryengine.engines.list"
  "logging.logEntries.list"
  "bigquery.tables.create"
  "bigquery.jobs.create"
)

PERM_CSV=$(IFS=,; echo "${REQUIRED_PERMS[*]}")
GRANTED_PERMS=$(gcloud projects test-iam-permissions "$PROJECT_ID" \
  --permissions="$PERM_CSV" \
  --format="value(permissions)" 2>/dev/null || true)

MISSING_PERMS=()
for perm in "${REQUIRED_PERMS[@]}"; do
  if ! echo "$GRANTED_PERMS" | grep -qw "$perm"; then
    MISSING_PERMS+=("$perm")
  fi
done

if [ ${#MISSING_PERMS[@]} -gt 0 ]; then
  echo "⚠️ Warning: Caller may be missing the following IAM permissions on '$PROJECT_ID':"
  for mp in "${MISSING_PERMS[@]}"; do
    echo "   - $mp"
  done
  echo ""
  echo "📋 Required Roles to ensure are granted:"
  echo "   • Service Usage Consumer:       roles/serviceusage.serviceUsageConsumer"
  echo "   • Discovery Engine Viewer:      roles/discoveryengine.viewer (or editor)"
  echo "   • Logs Viewer:                  roles/logging.viewer"
  echo "   • BigQuery Data Editor:         roles/bigquery.dataEditor"
  echo "   • BigQuery Job User:            roles/bigquery.jobUser"
  echo "------------------------------------------------------------------------------"
else
  echo "✅ IAM permissions verified: caller has required permissions."
fi
echo ""

# ------------------------------------------------------------------------------
# Section 2: Animated Stage Runner Helper
# ------------------------------------------------------------------------------
run_stage() {
  local stage_num="$1"
  local stage_title="$2"
  shift 2
  
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "🚀 [$stage_num] $stage_title"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  
  local log_file
  log_file=$(mktemp /tmp/ge_sync_stage.XXXXXX.log)
  local spin='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
  local i=0
  local start_time
  start_time=$(date +%s)
  
  # Run command/function in background redirected to log file
  ( "$@" ) > "$log_file" 2>&1 &
  local pid=$!
  
  while kill -0 "$pid" 2>/dev/null; do
    local now
    now=$(date +%s)
    local elapsed=$((now - start_time))
    local idx=$(( i % 10 ))
    printf "\r  ⏳ [%s] %s (${elapsed}s elapsed)..." "${spin:$idx:1}" "$stage_title"
    i=$((i + 1))
    sleep 0.15
  done
  
  local exit_code=0
  wait "$pid" || exit_code=$?
  local total_time=$(( $(date +%s) - start_time ))
  
  if [ $exit_code -eq 0 ]; then
    printf "\r  ✅ [%s] %s (Finished in %ds)               \n" "✓" "$stage_title" "$total_time"
    # Show key progress lines
    grep -E "✅|🎉|ℹ️|Found|Loading|Success|Triggering|Destination|Loaded|Export|Scanning|Fetching" "$log_file" | sed 's/^/     /' || true
    rm -f "$log_file"
    echo ""
  else
    printf "\r  ❌ [%s] %s (Failed after %ds)              \n" "✗" "$stage_title" "$total_time"
    echo ""
    echo "--- Stage Output Log ---"
    cat "$log_file"
    echo "------------------------"
    rm -f "$log_file"
    exit $exit_code
  fi
}

# ------------------------------------------------------------------------------
# Section 3: Stage Functions
# ------------------------------------------------------------------------------

# Stage 1: API Metadata Fetch
stage_fetch_api_metadata() {
  cd "$PARENT_DIR"
  $PYTHON_EXEC data_pipelines/fetch_agent_names.py
}

# Stage 2: Historical Creators Backfill (365 Days)
stage_backfill_creators() {
  local raw_file="/tmp/raw_creator_logs_$$.json"
  local output_file="/tmp/historical_creators_$$.jsonl"

  echo "Scanning Cloud Audit Logs for historical agent creations (past 365 days)..."
  gcloud logging read \
    'logName="projects/'"${PROJECT_ID}"'/logs/cloudaudit.googleapis.com%2Factivity" AND protoPayload.serviceName="discoveryengine.googleapis.com" AND protoPayload.methodName=~"CreateAgent"' \
    --project="${PROJECT_ID}" \
    --freshness=365d \
    --format="json" \
    --limit=10000 > "${raw_file}"

  if [ -s "${raw_file}" ] && [ "$(cat "${raw_file}")" != "[]" ]; then
    cat "${raw_file}" | jq -c '.[]? | {
      timestamp: .timestamp,
      creator_email: (.protoPayload.authenticationInfo.principalEmail // (.protoPayload.authenticationInfo.principalSubject | sub("^user:"; "") | split("/") | last) // "unknown_email"),
      agent_id: (((.protoPayload.request.agent.name // .protoPayload.response.name // .protoPayload.resourceName // "unknown/unknown_id") | split("/") | last) | tostring),
      display_name: (.protoPayload.request.agent.displayName // .protoPayload.response.displayName // "Unknown Name")
    }' > "${output_file}"

    local count
    count=$(wc -l < "${output_file}")
    echo "Loading ${count} historical creator records into ${PROJECT_ID}:${DATASET_ID}.historical_creators..."
    bq load \
      --project_id="${PROJECT_ID}" \
      --source_format=NEWLINE_DELIMITED_JSON \
      --schema="timestamp:TIMESTAMP,creator_email:STRING,agent_id:STRING,display_name:STRING" \
      --replace \
      "${PROJECT_ID}:${DATASET_ID}.historical_creators" \
      "${output_file}"
    echo "✅ Loaded ${count} creator records."
  else
    echo "ℹ️ No historical agent creation logs found in past 365 days."
  fi

  rm -f "${raw_file}" "${output_file}"
}

# Stage 3: Historical User Activity Backfill (365 Days)
stage_backfill_user_activity() {
  local raw_file="/tmp/raw_user_activity_$$.json"
  local output_file="/tmp/historical_user_activity_$$.jsonl"

  # Part A: Data Access Logs
  echo "Fetching historical Data Access audit logs (past 365 days)..."
  gcloud logging read \
    'logName="projects/'"${PROJECT_ID}"'/logs/cloudaudit.googleapis.com%2Fdata_access" AND protoPayload.serviceName="discoveryengine.googleapis.com"' \
    --project="${PROJECT_ID}" \
    --freshness=365d \
    --format="json" \
    --limit=50000 > "${raw_file}"

  if [ -s "${raw_file}" ] && [ "$(cat "${raw_file}")" != "[]" ]; then
    cat "${raw_file}" | jq -c '.[]? | 
      .protopayload_auditlog = .protoPayload | 
      del(.protoPayload) | 
      if .protopayload_auditlog.request then .protopayload_auditlog.requestJson = (.protopayload_auditlog.request | tojson) | del(.protopayload_auditlog.request) else . end | 
      del(.protopayload_auditlog.response) | 
      if .protopayload_auditlog.status then del(.protopayload_auditlog.status.details) else . end | 
      walk(if type == "object" then with_entries(select(.key | startswith("@") | not)) else . end)' > "${output_file}"

    local count
    count=$(wc -l < "${output_file}")
    echo "Loading ${count} Data Access records into ${PROJECT_ID}:${DATASET_ID}.cloudaudit_googleapis_com_data_access..."
    bq load \
      --project_id="${PROJECT_ID}" \
      --source_format=NEWLINE_DELIMITED_JSON \
      --max_bad_records=1000 \
      "${PROJECT_ID}:${DATASET_ID}.cloudaudit_googleapis_com_data_access" \
      "${output_file}"
    echo "✅ Loaded ${count} Data Access records."
  fi
  rm -f "${raw_file}" "${output_file}"

  # Part B: Gemini Enterprise User Activity Logs
  echo "Fetching historical User Activity logs (past 365 days)..."
  gcloud logging read \
    'logName="projects/'"${PROJECT_ID}"'/logs/discoveryengine.googleapis.com%2Fgemini_enterprise_user_activity"' \
    --project="${PROJECT_ID}" \
    --freshness=365d \
    --format="json" \
    --limit=50000 > "${raw_file}"

  if [ -s "${raw_file}" ] && [ "$(cat "${raw_file}")" != "[]" ]; then
    cat "${raw_file}" | jq -c '.[]? | {
      timestamp: .timestamp,
      insertId: .insertId,
      logName: .logName,
      severity: .severity,
      jsonPayload: {
        userIamPrincipal: .jsonPayload.userIamPrincipal,
        request: (if .jsonPayload.request.agentsSpec then { agentsSpec: { agentSpecs: [.jsonPayload.request.agentsSpec.agentSpecs[]? | { agentId: .agentId }] } } else null end),
        response: (if .jsonPayload.response.agentInfo then { agentInfo: { agent: .jsonPayload.response.agentInfo.agent, displayName: .jsonPayload.response.agentInfo.displayName } } else null end)
      }
    }' > "${output_file}"

    local count
    count=$(wc -l < "${output_file}")
    echo "Loading ${count} User Activity records into ${PROJECT_ID}:${DATASET_ID}.discoveryengine_googleapis_com_gemini_enterprise_user_activity..."
    bq load \
      --project_id="${PROJECT_ID}" \
      --source_format=NEWLINE_DELIMITED_JSON \
      --max_bad_records=1000 \
      "${PROJECT_ID}:${DATASET_ID}.discoveryengine_googleapis_com_gemini_enterprise_user_activity" \
      "${output_file}"
    echo "✅ Loaded ${count} User Activity records."
  fi
  rm -f "${raw_file}" "${output_file}"
}

# Stage 4: Sync Names & Export Metrics
stage_sync_names_and_metrics() {
  cd "$PARENT_DIR"
  
  echo "Synchronizing agent names from audit logs..."
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
  echo "✅ Display names synchronized."

  echo "Triggering Discovery Engine metrics export to BigQuery..."
  $PYTHON_EXEC data_pipelines/metrics_to_bq.py
}

# ------------------------------------------------------------------------------
# Section 4: Execute Pipeline Stages
# ------------------------------------------------------------------------------
TOTAL_START=$(date +%s)

run_stage "1/4" "Fetching Live Agent Metadata from Vertex AI API" stage_fetch_api_metadata
run_stage "2/4" "Backfilling Historical Creators from Cloud Audit Logs (365 Days)" stage_backfill_creators
run_stage "3/4" "Backfilling Historical User Activity Logs (365 Days)" stage_backfill_user_activity
run_stage "4/4" "Synchronizing Agent Directory & Triggering BigQuery Metrics Export" stage_sync_names_and_metrics

TOTAL_ELAPSED=$(( $(date +%s) - TOTAL_START ))

echo "=============================================================================="
echo "🎉 Initial Data Ingestion & Backfill completed in ${TOTAL_ELAPSED}s!"
echo "All BigQuery tables and views in dataset '${DATASET_ID}' are fully populated."
echo "=============================================================================="

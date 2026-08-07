#!/bin/bash
# ==============================================================================
# Script Name: setup_infra.sh
# Description:
#   One-stop infrastructure provisioning script for Gemini Enterprise Analytics.
#   Provisions:
#     1. BigQuery Dataset and Base Tables (creates schemas if not existing)
#     2. Cloud Logging Sinks (Creation Audit Logs & User Activity Telemetry) + IAM
#     3. Enriched BigQuery Views (vw_unified_metrics, vw_user_feature_adoption, vw_feature_adoption_summary)
#
# Requirements:
#   - gcloud SDK and bq CLI authenticated.
#   - .env file in analytics_pipeline/ with PROJECT_ID and DATASET_ID.
# ==============================================================================

set -e

# ------------------------------------------------------------------------------
# Section 1: Environment & Validation
# ------------------------------------------------------------------------------
if [ -f .env ]; then
  echo "🔍 Loading environment variables from .env..."
  set -a
  source .env
  set +a
else
  echo "⚠️ .env file not found. Falling back to environment variables."
fi

if [ -z "$PROJECT_ID" ]; then
  echo "❌ Error: PROJECT_ID is not set. Please define PROJECT_ID in .env file."
  exit 1
fi

if [ -z "$DATASET_ID" ]; then
  echo "❌ Error: DATASET_ID is not set. Please define DATASET_ID in .env file."
  exit 1
fi

LOCATION=${BQ_LOCATION:-US}
SINK_NAME=${SINK_NAME:-gemini_agent_creators}
USAGE_SINK_NAME=${USAGE_SINK_NAME:-gemini_usage_activity_sink}
TABLE_ID="agent_session_metrics"
UNIFIED_VIEW_ID="vw_unified_metrics"
USER_VIEW_ID="vw_user_feature_adoption"
SUMMARY_VIEW_ID="vw_feature_adoption_summary"

echo "=============================================================================="
echo "🚀 Provisioning Infrastructure for Gemini Enterprise Analytics"
echo "Project ID:      $PROJECT_ID"
echo "Dataset ID:      $DATASET_ID"
echo "Location:        $LOCATION"
echo "=============================================================================="

# ------------------------------------------------------------------------------
# Section 2: BigQuery Dataset & Base Tables
# ------------------------------------------------------------------------------
echo ""
echo "🚀 [1/3] Setting up BigQuery Dataset and Base Tables..."

if ! bq show "${PROJECT_ID}:${DATASET_ID}" > /dev/null 2>&1; then
  echo "Creating dataset '${DATASET_ID}' in location '${LOCATION}'..."
  bq mk --location="${LOCATION}" --dataset "${PROJECT_ID}:${DATASET_ID}"
  echo "✅ Dataset created."
else
  echo "ℹ️ Dataset '${DATASET_ID}' already exists."
fi

echo "🔍 Initializing base table schemas..."
bq query --use_legacy_sql=false "
CREATE TABLE IF NOT EXISTS \`${PROJECT_ID}.${DATASET_ID}.${TABLE_ID}\` (
  date DATE,
  agent_name STRING,
  agent_session_count INT64,
  monthly_agent_active_user_count INT64
);

CREATE TABLE IF NOT EXISTS \`${PROJECT_ID}.${DATASET_ID}.agent_names\` (
  agent_id STRING,
  display_name STRING,
  description STRING,
  system_instructions STRING,
  datastore_ids STRING,
  datastore_names STRING,
  agent_type STRING,
  sub_agents STRING
);

CREATE TABLE IF NOT EXISTS \`${PROJECT_ID}.${DATASET_ID}.historical_creators\` (
  timestamp TIMESTAMP,
  creator_email STRING,
  agent_id STRING,
  display_name STRING
);

-- Auto-migrate existing tables if missing columns
ALTER TABLE \`${PROJECT_ID}.${DATASET_ID}.historical_creators\` ADD COLUMN IF NOT EXISTS display_name STRING;
ALTER TABLE \`${PROJECT_ID}.${DATASET_ID}.agent_names\` ADD COLUMN IF NOT EXISTS system_instructions STRING;
ALTER TABLE \`${PROJECT_ID}.${DATASET_ID}.agent_names\` ADD COLUMN IF NOT EXISTS datastore_ids STRING;
ALTER TABLE \`${PROJECT_ID}.${DATASET_ID}.agent_names\` ADD COLUMN IF NOT EXISTS datastore_names STRING;
ALTER TABLE \`${PROJECT_ID}.${DATASET_ID}.agent_names\` ADD COLUMN IF NOT EXISTS sub_agents STRING;

CREATE TABLE IF NOT EXISTS \`${PROJECT_ID}.${DATASET_ID}.cloudaudit_googleapis_com_data_access\` (
  timestamp TIMESTAMP,
  logName STRING,
  insertId STRING,
  severity STRING,
  protopayload_auditlog JSON
);

CREATE TABLE IF NOT EXISTS \`${PROJECT_ID}.${DATASET_ID}.discoveryengine_googleapis_com_gemini_enterprise_user_activity\` (
  timestamp TIMESTAMP,
  logName STRING,
  insertId STRING,
  severity STRING,
  jsonPayload JSON
);

CREATE TABLE IF NOT EXISTS \`${PROJECT_ID}.${DATASET_ID}.discoveryengine_googleapis_com_notebooklm_enterprise_user_activity\` (
  timestamp TIMESTAMP,
  logName STRING,
  insertId STRING,
  severity STRING,
  jsonPayload JSON
);
"
echo "✅ Base tables initialized."

# ------------------------------------------------------------------------------
# Section 3: Cloud Logging Sinks & IAM Permissions
# ------------------------------------------------------------------------------
echo ""
echo "🚀 [2/3] Setting up Cloud Logging Sinks & Observability..."

echo "Enabling Gemini Notebook Enterprise Observability Audit Logging..."
TOKEN=$(gcloud auth print-access-token 2>/dev/null)
if [ -n "${TOKEN}" ]; then
  curl -s -X PATCH \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -H "X-Goog-User-Project: ${PROJECT_ID}" \
    "https://discoveryengine.googleapis.com/v1alpha/projects/${PROJECT_ID}?updateMask=customerProvidedConfig.notebooklmConfig.observabilityConfig" \
    -d '{
      "customerProvidedConfig": {
        "notebooklmConfig": {
          "observabilityConfig": {
            "observabilityEnabled": true,
            "sensitiveLoggingEnabled": true
          }
        }
      }
    }' > /dev/null && echo "✅ NotebookLM Enterprise Observability enabled." || echo "ℹ️ Failed to auto-enable NotebookLM observability."
fi

# Sink 1: Agent Creation Events
echo "Configuring Log Sink '${SINK_NAME}'..."
gcloud logging sinks create "${SINK_NAME}" \
  "bigquery.googleapis.com/projects/${PROJECT_ID}/datasets/${DATASET_ID}" \
  --log-filter='protoPayload.serviceName="discoveryengine.googleapis.com" AND protoPayload.methodName="google.cloud.discoveryengine.v1.EngineService.CreateEngine"' \
  --use-partitioned-tables \
  --project="${PROJECT_ID}" || echo "ℹ️ Sink '${SINK_NAME}' may already exist."

SINK_SA_1=$(gcloud logging sinks describe "${SINK_NAME}" --project="${PROJECT_ID}" --format='value(writerIdentity)')
echo "Granting BigQuery Data Editor access to: ${SINK_SA_1}..."
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="${SINK_SA_1}" \
  --role="roles/bigquery.dataEditor" \
  --condition=None || echo "⚠️ Please ask an IAM admin to grant roles/bigquery.dataEditor to ${SINK_SA_1}"

# Sink 2: Real-time User Activity Logs
echo "Configuring Log Sink '${USAGE_SINK_NAME}'..."
gcloud logging sinks create "${USAGE_SINK_NAME}" \
  "bigquery.googleapis.com/projects/${PROJECT_ID}/datasets/${DATASET_ID}" \
  --log-filter='
    logName="projects/'"${PROJECT_ID}"'/logs/discoveryengine.googleapis.com%2Fgemini_enterprise_user_activity"
    OR logName="projects/'"${PROJECT_ID}"'/logs/discoveryengine.googleapis.com%2Fnotebooklm_enterprise_user_activity"
    OR (protoPayload.serviceName="discoveryengine.googleapis.com" AND (
      protoPayload.methodName="google.cloud.discoveryengine.v1.AssistantService.Assist"
      OR protoPayload.methodName="google.cloud.discoveryengine.v1.AssistantService.StreamAssist"
      OR protoPayload.methodName="google.cloud.discoveryengine.v1.NotebookService.CreateNotebook"
      OR protoPayload.methodName="google.cloud.discoveryengine.v1.NotebookService.GetNotebook"
      OR protoPayload.methodName="google.cloud.discoveryengine.v1.NotebookService.InteractSources"
      OR protoPayload.methodName="google.cloud.discoveryengine.v1.NotebookService.GenerateFreeFormStreamed"
    ))' \
  --use-partitioned-tables \
  --project="${PROJECT_ID}" || echo "ℹ️ Sink '${USAGE_SINK_NAME}' may already exist."

SINK_SA_2=$(gcloud logging sinks describe "${USAGE_SINK_NAME}" --project="${PROJECT_ID}" --format='value(writerIdentity)')
echo "Granting BigQuery Data Editor access to: ${SINK_SA_2}..."
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="${SINK_SA_2}" \
  --role="roles/bigquery.dataEditor" \
  --condition=None || echo "⚠️ Please ask an IAM admin to grant roles/bigquery.dataEditor to ${SINK_SA_2}"

echo "✅ Log sinks configured."

# ------------------------------------------------------------------------------
# Section 4: Enriched BigQuery Views
# ------------------------------------------------------------------------------
echo ""
echo "🚀 [3/3] Creating Enriched BigQuery Views..."

# View 1: Unified Metrics Leaderboard View
echo "Creating view '${UNIFIED_VIEW_ID}'..."
bq query --use_legacy_sql=false "
CREATE OR REPLACE VIEW \`${PROJECT_ID}.${DATASET_ID}.${UNIFIED_VIEW_ID}\` AS
SELECT 
  SPLIT(ml.agent_name, '/')[OFFSET(ARRAY_LENGTH(SPLIT(ml.agent_name, '/')) - 1)] as agent_id,
  COALESCE(NULLIF(an.display_name, ''), SPLIT(ml.agent_name, '/')[OFFSET(ARRAY_LENGTH(SPLIT(ml.agent_name, '/')) - 1)]) as display_name,
  SUM(ml.agent_session_count) as total_sessions,
  MAX(ml.monthly_agent_active_user_count) as monthly_users,
  MIN(ml.date) as first_active_date,
  MAX(ml.date) as last_active_date
FROM \`${PROJECT_ID}.${DATASET_ID}.${TABLE_ID}\` ml
LEFT JOIN \`${PROJECT_ID}.${DATASET_ID}.agent_names\` an 
  ON SPLIT(ml.agent_name, '/')[OFFSET(ARRAY_LENGTH(SPLIT(ml.agent_name, '/')) - 1)] = an.agent_id
GROUP BY agent_id, display_name;
"

# View 2: Normalized Daily User Feature Adoption View
echo "Creating view '${USER_VIEW_ID}'..."
bq query --use_legacy_sql=false "
CREATE OR REPLACE VIEW \`${PROJECT_ID}.${DATASET_ID}.${USER_VIEW_ID}\` AS
WITH normalized_logs AS (
  SELECT
    JSON_VALUE(protopayload_auditlog, '$.authenticationInfo.principalEmail') AS user_email,
    DATE(timestamp) AS activity_date,
    (JSON_VALUE(protopayload_auditlog, '$.serviceName') = 'discoveryengine.googleapis.com'
     AND JSON_VALUE(protopayload_auditlog, '$.methodName') LIKE '%AssistantService%'
     AND (COALESCE(JSON_VALUE(protopayload_auditlog, '$.request.agent_info.core_assistant'), JSON_VALUE(protopayload_auditlog, '$.requestJson.agent_info.core_assistant')) = 'true'
          OR (COALESCE(JSON_VALUE(protopayload_auditlog, '$.request.agent_info.agent'), JSON_VALUE(protopayload_auditlog, '$.requestJson.agent_info.agent')) IS NULL 
              AND COALESCE(JSON_VALUE(protopayload_auditlog, '$.request.agents_spec'), JSON_VALUE(protopayload_auditlog, '$.requestJson.agents_spec')) IS NULL))) AS is_chat,

    (JSON_VALUE(protopayload_auditlog, '$.serviceName') = 'discoveryengine.googleapis.com'
     AND JSON_VALUE(protopayload_auditlog, '$.methodName') LIKE '%AssistantService%'
     AND (COALESCE(JSON_VALUE(protopayload_auditlog, '$.request.agent_info.agent'), JSON_VALUE(protopayload_auditlog, '$.requestJson.agent_info.agent')) IS NOT NULL
          OR COALESCE(JSON_VALUE(protopayload_auditlog, '$.request.agents_spec'), JSON_VALUE(protopayload_auditlog, '$.requestJson.agents_spec')) IS NOT NULL)
     AND COALESCE(
           JSON_VALUE(protopayload_auditlog, '$.request.agent_info.agent'),
           JSON_VALUE(protopayload_auditlog, '$.requestJson.agent_info.agent'),
           JSON_VALUE(protopayload_auditlog, '$.request.agents_spec.agent_specs[0].agent_id'),
           JSON_VALUE(protopayload_auditlog, '$.requestJson.agents_spec.agent_specs[0].agent_id')
         ) NOT IN ('workflow_summary_agent', 'default_assistant')) AS is_agent,

    (logName LIKE '%notebooklm%'
     OR JSON_VALUE(protopayload_auditlog, '$.methodName') LIKE '%NotebookService%'
     OR JSON_VALUE(protopayload_auditlog, '$.methodName') LIKE '%SourceService%'
     OR JSON_VALUE(protopayload_auditlog, '$.methodName') LIKE '%AudioOverviewService%') AS is_nblm,

    IF(
      COALESCE(
        JSON_VALUE(protopayload_auditlog, '$.request.agent_info.agent'),
        JSON_VALUE(protopayload_auditlog, '$.requestJson.agent_info.agent'),
        JSON_VALUE(protopayload_auditlog, '$.request.agents_spec.agent_specs[0].agent_id'),
        JSON_VALUE(protopayload_auditlog, '$.requestJson.agents_spec.agent_specs[0].agent_id')
      ) IN ('workflow_summary_agent', 'default_assistant'),
      NULL,
      COALESCE(
        JSON_VALUE(protopayload_auditlog, '$.request.agent_info.agent'),
        JSON_VALUE(protopayload_auditlog, '$.requestJson.agent_info.agent'),
        JSON_VALUE(protopayload_auditlog, '$.request.agents_spec.agent_specs[0].agent_id'),
        JSON_VALUE(protopayload_auditlog, '$.requestJson.agents_spec.agent_specs[0].agent_id')
      )
    ) AS agent_id
  FROM \`${PROJECT_ID}.${DATASET_ID}.cloudaudit_googleapis_com_data_access\`
  WHERE JSON_VALUE(protopayload_auditlog, '$.authenticationInfo.principalEmail') IS NOT NULL

  UNION ALL

  SELECT
    JSON_VALUE(jsonPayload, '$.userIamPrincipal') AS user_email,
    DATE(timestamp) AS activity_date,
    (JSON_VALUE(jsonPayload, '$.request.agentsSpec') IS NULL 
     AND JSON_VALUE(jsonPayload, '$.response.agentInfo.agent') IS NULL) AS is_chat,

    ((JSON_VALUE(jsonPayload, '$.request.agentsSpec') IS NOT NULL 
      OR JSON_VALUE(jsonPayload, '$.response.agentInfo.agent') IS NOT NULL)
     AND COALESCE(
           JSON_VALUE(jsonPayload, '$.response.agentInfo.agent'),
           JSON_VALUE(jsonPayload, '$.request.agentsSpec.agentSpecs[0].agentId')
         ) NOT IN ('workflow_summary_agent', 'default_assistant')) AS is_agent,

    (logName LIKE '%notebooklm%') AS is_nblm,

    IF(
      COALESCE(
        JSON_VALUE(jsonPayload, '$.response.agentInfo.agent'),
        JSON_VALUE(jsonPayload, '$.request.agentsSpec.agentSpecs[0].agentId')
      ) IN ('workflow_summary_agent', 'default_assistant'),
      NULL,
      COALESCE(
        JSON_VALUE(jsonPayload, '$.response.agentInfo.agent'),
        JSON_VALUE(jsonPayload, '$.request.agentsSpec.agentSpecs[0].agentId')
      )
    ) AS agent_id
  FROM \`${PROJECT_ID}.${DATASET_ID}.discoveryengine_googleapis_com_gemini_enterprise_user_activity\`
  WHERE JSON_VALUE(jsonPayload, '$.userIamPrincipal') IS NOT NULL

  UNION ALL

  SELECT
    COALESCE(
      JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.userIamPrincipal'),
      JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.useriamprincipal'),
      jsonPayload.useriamprincipal
    ) AS user_email,
    DATE(timestamp) AS activity_date,
    FALSE AS is_chat,
    FALSE AS is_agent,
    TRUE AS is_nblm,
    CAST(NULL AS STRING) AS agent_id
  FROM \`${PROJECT_ID}.${DATASET_ID}.discoveryengine_googleapis_com_notebooklm_enterprise_user_activity\`
  WHERE COALESCE(
    JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.userIamPrincipal'),
    JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.useriamprincipal'),
    jsonPayload.useriamprincipal
  ) IS NOT NULL
)
SELECT
  user_email,
  activity_date,
  LOGICAL_OR(is_chat) AS used_chat,
  LOGICAL_OR(is_agent) AS used_agents,
  LOGICAL_OR(is_nblm) AS used_notebooklm,
  ARRAY_AGG(DISTINCT agent_id IGNORE NULLS) AS agent_ids_used
FROM normalized_logs
GROUP BY user_email, activity_date;
"

# View 3: Master Feature Adoption Summary View
echo "Creating view '${SUMMARY_VIEW_ID}'..."
bq query --use_legacy_sql=false "
CREATE OR REPLACE VIEW \`${PROJECT_ID}.${DATASET_ID}.${SUMMARY_VIEW_ID}\` AS
WITH daily_user_flags AS (
  SELECT
    activity_date,
    user_email,
    used_chat AS chat,
    used_notebooklm AS nblm,
    used_agents AS agents
  FROM \`${PROJECT_ID}.${DATASET_ID}.${USER_VIEW_ID}\`
),
daily_agent_counts AS (
  SELECT
    activity_date,
    COUNT(DISTINCT agent_id) AS distinct_agents_used
  FROM \`${PROJECT_ID}.${DATASET_ID}.${USER_VIEW_ID}\`,
  UNNEST(agent_ids_used) AS agent_id
  GROUP BY activity_date
),
daily_totals AS (
  SELECT
    u.activity_date,
    COUNT(DISTINCT u.user_email) AS total_active_users,
    COUNTIF(u.chat) AS chat_users,
    COUNTIF(u.nblm) AS notebooklm_users,
    COUNTIF(u.agents) AS agent_users,
    COALESCE(MAX(a.distinct_agents_used), 0) AS distinct_agents_used,
    COUNTIF(u.chat AND u.nblm) AS chat_and_notebooklm_users,
    COUNTIF(u.chat AND u.agents) AS chat_and_agents_users,
    COUNTIF(u.nblm AND u.agents) AS notebooklm_and_agents_users,
    COUNTIF(u.chat AND u.nblm AND u.agents) AS all_three_users
  FROM daily_user_flags u
  LEFT JOIN daily_agent_counts a ON u.activity_date = a.activity_date
  GROUP BY u.activity_date
)
SELECT
  activity_date AS time_period,
  total_active_users,
  chat_users,
  ROUND(chat_users * 100.0 / NULLIF(total_active_users, 0), 2) AS chat_pct,
  notebooklm_users,
  ROUND(notebooklm_users * 100.0 / NULLIF(total_active_users, 0), 2) AS notebooklm_pct,
  agent_users,
  ROUND(agent_users * 100.0 / NULLIF(total_active_users, 0), 2) AS agent_pct,
  distinct_agents_used,
  chat_and_notebooklm_users,
  ROUND(chat_and_notebooklm_users * 100.0 / NULLIF(total_active_users, 0), 2) AS chat_and_notebooklm_pct,
  chat_and_agents_users,
  ROUND(chat_and_agents_users * 100.0 / NULLIF(total_active_users, 0), 2) AS chat_and_agents_pct,
  notebooklm_and_agents_users,
  ROUND(notebooklm_and_agents_users * 100.0 / NULLIF(total_active_users, 0), 2) AS notebooklm_and_agents_pct,
  all_three_users,
  ROUND(all_three_users * 100.0 / NULLIF(total_active_users, 0), 2) AS all_three_pct
FROM daily_totals
ORDER BY activity_date DESC;
"

# View 4: Agent Creators Joined View
echo "Creating view 'vw_agent_creators'..."
bq query --use_legacy_sql=false "
CREATE OR REPLACE VIEW \`${PROJECT_ID}.${DATASET_ID}.vw_agent_creators\` AS
SELECT 
  hc.creator_email,
  hc.timestamp AS creation_time,
  hc.agent_id,
  COALESCE(NULLIF(an.display_name, ''), hc.agent_id) AS display_name,
  an.agent_type,
  an.description,
  an.system_instructions
FROM \`${PROJECT_ID}.${DATASET_ID}.historical_creators\` hc
LEFT JOIN \`${PROJECT_ID}.${DATASET_ID}.agent_names\` an
  ON hc.agent_id = an.agent_id
ORDER BY hc.timestamp DESC;
"

echo "✅ All BigQuery views created successfully."
echo ""
echo "🎉 Infrastructure provisioning complete! Your dataset '${DATASET_ID}' is ready."

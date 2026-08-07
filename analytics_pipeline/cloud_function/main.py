import os
import sys
import json
import time
import requests
import functions_framework
from google.auth import default
from google.auth.transport.requests import Request
from google.cloud import bigquery

def get_auth_token():
    """Obtains access token from default credentials."""
    credentials, _ = default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
    credentials.refresh(Request())
    return credentials.token

def fetch_and_sync_agent_names(project_id, location, engine_id, dataset_id):
    """Step 1: Fetch active agent definitions and update BigQuery agent_names table."""
    token = get_auth_token()
    base_url = f"https://discoveryengine.googleapis.com/v1alpha/projects/{project_id}/locations/{location}/collections/default_collection/engines/{engine_id}/assistants/default_assistant/agents"
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
        'x-goog-user-project': project_id
    }
    
    # 1. Fetch agents
    agents = []
    page_token = None
    params = {}
    while True:
        res = requests.get(base_url, headers=headers, params=params)
        if res.status_code != 200:
            print(f"⚠️ Error fetching agents: {res.status_code} - {res.text}")
            break
        data = res.json()
        agents.extend(data.get("agents", []))
        page_token = data.get("nextPageToken")
        if not page_token:
            break
        params["pageToken"] = page_token

    # 2. Format records
    rows_to_insert = []
    for agent in agents:
        agent_name_path = agent.get("name", "")
        agent_id = agent_name_path.split("/")[-1] if agent_name_path else ""
        if not agent_id or agent_id in ['workflow_summary_agent', 'default_assistant']:
            continue
            
        display_name = agent.get("displayName", "")
        description = agent.get("description", "")
        
        agent_type = "Agent Designer"
        if "adkAgentDefinition" in agent:
            agent_type = "ADK Agent"
        elif "managedAgentDefinition" in agent:
            agent_type = "Managed Agent"
            
        system_instructions = ""
        low_code = agent.get("lowCodeAgentDefinition", {})
        nodes = low_code.get("nodes", []) or low_code.get("deployedNodes", [])
        if nodes:
            llm_node = nodes[0].get("llmAgentNode", {})
            system_instructions = llm_node.get("instruction", "")
            
        rows_to_insert.append({
            "agent_id": agent_id,
            "display_name": display_name,
            "agent_type": agent_type,
            "description": description,
            "system_instructions": system_instructions
        })

    # 3. Upsert into BigQuery
    bq_client = bigquery.Client(project=project_id)
    table_ref = f"{project_id}.{dataset_id}.agent_names"
    
    if rows_to_insert:
        # Load via temporary table or direct merge
        staging_table = f"{project_id}.{dataset_id}._staging_agent_names"
        job_config = bigquery.LoadJobConfig(
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
            autodetect=True
        )
        load_job = bq_client.load_table_from_json(rows_to_insert, staging_table, job_config=job_config)
        load_job.result()
        
        merge_sql = f"""
        MERGE INTO `{table_ref}` T
        USING `{staging_table}` S
        ON T.agent_id = S.agent_id
        WHEN MATCHED THEN
          UPDATE SET 
            display_name = S.display_name,
            agent_type = S.agent_type,
            description = S.description,
            system_instructions = S.system_instructions
        WHEN NOT MATCHED THEN
          INSERT (agent_id, display_name, agent_type, description, system_instructions)
          VALUES (S.agent_id, S.display_name, S.agent_type, S.description, S.system_instructions);
        """
        bq_client.query(merge_sql).result()
        bq_client.delete_table(staging_table, not_found_ok=True)
        print(f"✅ Upserted {len(rows_to_insert)} agent definitions into {table_ref}.")

    return len(rows_to_insert)

def reconcile_audit_log_names(project_id, dataset_id):
    """Step 2: Reconcile display names from real-time BigQuery user activity logs."""
    bq_client = bigquery.Client(project=project_id)
    reconcile_sql = f"""
    MERGE INTO `{project_id}.{dataset_id}.agent_names` T
    USING (
      SELECT DISTINCT
        JSON_VALUE(jsonPayload, '$.request.agentsSpec.agentSpecs[0].agentId') AS agent_id,
        JSON_VALUE(jsonPayload, '$.response.agentInfo.displayName') AS display_name,
        'Agent Designer' AS agent_type
      FROM `{project_id}.{dataset_id}.discoveryengine_googleapis_com_gemini_enterprise_user_activity`
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
    """
    try:
        bq_client.query(reconcile_sql).result()
        print("✅ Reconciled agent names from BigQuery user activity logs.")
    except Exception as e:
        print(f"ℹ️ Reconcile skipped or table empty: {e}")

def trigger_metrics_export(project_id, location, engine_input, dataset_id):
    """Step 3: Trigger Discovery Engine exportMetrics API across single, array, or auto-discovered engines."""
    token = get_auth_token()
    target_engines = []
    
    if engine_input and engine_input.upper() not in ["ALL", "AUTO", "*"]:
        target_engines = [e.strip() for e in engine_input.split(",") if e.strip()]
    else:
        # Auto-discover all engines in project
        list_url = f"https://discoveryengine.googleapis.com/v1/projects/{project_id}/locations/{location}/collections/default_collection/engines"
        headers = {'Authorization': f'Bearer {token}', 'x-goog-user-project': project_id}
        try:
            res = requests.get(list_url, headers=headers, timeout=(10, 20))
            if res.status_code == 200:
                engines_list = res.json().get("engines", [])
                target_engines = [e.get("name", "").split("/")[-1] for e in engines_list if e.get("name")]
        except Exception as e:
            print(f"⚠️ Auto-discovery error: {e}")
            
    if not target_engines:
        target_engines = [engine_input] if engine_input else []
        
    operations = []
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
        'x-goog-user-project': project_id
    }
    payload = {
        "outputConfig": {
            "bigqueryDestination": {
                "datasetId": dataset_id,
                "tableId": "agent_session_metrics"
            }
        }
    }
    
    for engine_id in target_engines:
        url = f"https://discoveryengine.googleapis.com/v1alpha/projects/{project_id}/locations/{location}/collections/default_collection/engines/{engine_id}/analytics:exportMetrics"
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=(10, 20))
            if res.status_code == 200:
                op_name = res.json().get('name')
                operations.append(f"{engine_id}: {op_name}")
                print(f"✅ Triggered export for '{engine_id}'. Op: {op_name}")
            else:
                print(f"⚠️ Export skipped/failed for '{engine_id}': {res.status_code}")
        except Exception as e:
            print(f"⚠️ Export error for '{engine_id}': {e}")
            
    return (len(operations) > 0), ", ".join(operations)

@functions_framework.http
def sync_metrics(request):
    """HTTP Cloud Function Entrypoint for Cloud Scheduler or manual trigger."""
    project_id = os.getenv("PROJECT_ID", "genai-ge-app")
    engine_input = os.getenv("ENGINE_ID", "ALL")
    dataset_id = os.getenv("DATASET_ID", "ge_metrics")
    location = os.getenv("GE_LOCATION", "global")
    
    print(f"🚀 Starting Nightly Analytics Sync for Project: {project_id}, Dataset: {dataset_id}")
    
    try:
        # Step 1: Live agent metadata across all engines
        agent_count = fetch_and_sync_agent_names(project_id, location, engine_input, dataset_id)
        
        # Step 2: Audit log name reconciliation
        reconcile_audit_log_names(project_id, dataset_id)
        
        # Step 3: Discovery Engine session metrics export across all target engines
        export_ok, op_detail = trigger_metrics_export(project_id, location, engine_input, dataset_id)
        
        response_data = {
            "status": "success",
            "project_id": project_id,
            "dataset_id": dataset_id,
            "agents_synced": agent_count,
            "export_triggered": export_ok,
            "operations": op_detail
        }
        return (json.dumps(response_data), 200, {'Content-Type': 'application/json'})
    except Exception as e:
        error_msg = f"❌ Sync execution failed: {str(e)}"
        print(error_msg)
        return (json.dumps({"status": "error", "message": str(e)}), 500, {'Content-Type': 'application/json'})

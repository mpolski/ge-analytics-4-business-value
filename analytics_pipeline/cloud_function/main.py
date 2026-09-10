import os
import sys
import json
import re
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

def extract_connector_info(conn_name, data_source=None):
    """Extracts clean connector_id and connector_type from resource paths or dataSource."""
    conn_id = ""
    if conn_name:
        m = re.search(r'collections/([^/]+)/dataConnector', conn_name)
        if m:
            conn_id = m.group(1)
        else:
            parts = conn_name.strip("/").split("/")
            if len(parts) >= 2 and parts[-1] == "dataConnector":
                conn_id = parts[-2]
            elif parts[-1] != "dataConnector":
                conn_id = parts[-1]
                
    ctype = data_source or ""
    if not ctype and conn_id:
        ctype = conn_id.split("_")[0].split("-")[0]
    return conn_id, ctype

def fetch_and_sync_agent_names(project_id, location, engine_id, dataset_id):
    """Step 1: Fetch active agent definitions and update BigQuery agent_names table."""
    token = get_auth_token()
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
        'x-goog-user-project': project_id
    }
    
    # 0. Pre-fetch datastores for display name resolution
    ds_lookup = {}
    try:
        ds_url = f"https://discoveryengine.googleapis.com/v1/projects/{project_id}/locations/{location}/collections/default_collection/dataStores"
        ds_res = requests.get(ds_url, headers=headers, timeout=(10, 20))
        if ds_res.status_code == 200:
            for ds in ds_res.json().get("dataStores", []):
                ds_id = ds.get("name", "").split("/")[-1]
                if ds_id:
                    ds_lookup[ds_id] = ds.get("displayName", ds_id)
    except Exception as e:
        print(f"⚠️ Could not pre-fetch data stores: {e}")

    # Determine target engines
    target_engines = []
    if engine_id and engine_id.upper() not in ["ALL", "AUTO", "*"]:
        target_engines = [e.strip() for e in engine_id.split(",") if e.strip()]
    else:
        list_url = f"https://discoveryengine.googleapis.com/v1/projects/{project_id}/locations/{location}/collections/default_collection/engines"
        try:
            res = requests.get(list_url, headers=headers, timeout=(10, 20))
            if res.status_code == 200:
                target_engines = [e.get("name", "").split("/")[-1] for e in res.json().get("engines", []) if e.get("name")]
        except Exception as e:
            print(f"⚠️ Auto-discovery error: {e}")

    if not target_engines and engine_id:
        target_engines = [engine_id]

    rows_to_insert = []
    for eng in target_engines:
        base_url = f"https://discoveryengine.googleapis.com/v1alpha/projects/{project_id}/locations/{location}/collections/default_collection/engines/{eng}/assistants/default_assistant/agents"
        agents = []
        page_token = None
        params = {}
        while True:
            res = requests.get(base_url, headers=headers, params=params)
            if res.status_code != 200:
                print(f"⚠️ Error fetching agents for engine {eng}: {res.status_code} - {res.text}")
                break
            data = res.json()
            agents.extend(data.get("agents", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                break
            params["pageToken"] = page_token

        for agent in agents:
            agent_name_path = agent.get("name", "")
            aid = agent_name_path.split("/")[-1] if agent_name_path else ""
            if not aid or aid in ['workflow_summary_agent', 'default_assistant']:
                continue
                
            display_name = agent.get("displayName", agent.get("draftDisplayName", "Unknown"))
            description = agent.get("description", agent.get("draftDescription", ""))
            
            agent_type = "Unknown"
            system_instructions = ""
            sub_agents_str = ""
            agent_datastore_ids = set()
            agent_connector_ids = set()
            agent_connector_types = set()

            if "adkAgentDefinition" in agent:
                agent_type = "ADK Agent"
            elif "lowCodeAgentDefinition" in agent:
                agent_type = "Agent Builder (UI)"
                builder_def = agent["lowCodeAgentDefinition"]
                agents_list = builder_def.get("deployedNodes", builder_def.get("draftAgents", builder_def.get("nodes", builder_def.get("agents", []))))
                root_id = builder_def.get("deployedRootAgentId", builder_def.get("rootAgentId", builder_def.get("draftRootAgentId", "root_agent")))
                
                sub_instructions = []
                sub_agent_names = []
                for a in agents_list:
                    node = a.get("llmAgentNode", {})
                    inst = node.get("instruction", "")
                    if a.get("id") != root_id:
                        sub_agent_names.append(a.get('displayName', 'Sub-Agent'))
                    if inst:
                        if a.get("id") == root_id:
                            system_instructions = inst + "\n\n" + system_instructions
                        else:
                            sub_instructions.append(f"[{a.get('displayName', 'Sub-Agent')}] {inst}")
                    for spec in node.get("dataStoreSpecs", {}).get("specs", []):
                        ds = spec.get("dataStore", "").split("/")[-1]
                        if ds: agent_datastore_ids.add(ds)
                    for conn in node.get("dataConnectors", []):
                        cid, ctype = extract_connector_info(conn.get("name", ""), conn.get("dataSource"))
                        if cid: agent_connector_ids.add(cid)
                        if ctype: agent_connector_types.add(ctype)
                    for sel in node.get("connectorToolSelections", []):
                        dc = sel.get("dataConnector", {})
                        cid, ctype = extract_connector_info(dc.get("name", ""), dc.get("dataSource"))
                        if cid: agent_connector_ids.add(cid)
                        if ctype: agent_connector_types.add(ctype)
                if sub_instructions:
                    system_instructions += "\nSub-Agent Instructions:\n" + "\n".join(sub_instructions)
                sub_agents_str = ", ".join(sub_agent_names)

            elif "workflowAgentDefinition" in agent:
                agent_type = "Workflow Agent"
                wf = agent["workflowAgentDefinition"]
                agent_flow = wf.get("agentFlow", {})
                flow_nodes = agent_flow.get("nodes", []) or wf.get("workflowDefinition", {}).get("nodes", [])
                wf_instructions = []
                for fn in flow_nodes:
                    trig = fn.get("connectorEventTrigger", {})
                    if trig:
                        dc = trig.get("dataConnector", {})
                        cid, ctype = extract_connector_info(dc.get("name", ""), dc.get("dataSource"))
                        if cid: agent_connector_ids.add(cid)
                        if ctype: agent_connector_types.add(ctype)
                        for spec in trig.get("dataStoreSpecs", {}).get("specs", []):
                            ds = spec.get("dataStore", "").split("/")[-1]
                            if ds: agent_datastore_ids.add(ds)
                    ag_node = fn.get("agentNode", {})
                    if ag_node:
                        inst = ag_node.get("instruction", "")
                        dname = fn.get("displayName", fn.get("id", "Agent Node"))
                        if inst: wf_instructions.append(f"[{dname}] {inst}")
                        for sel in ag_node.get("connectorToolSelections", []):
                            dc = sel.get("dataConnector", {})
                            cid, ctype = extract_connector_info(dc.get("name", ""), dc.get("dataSource"))
                            if cid: agent_connector_ids.add(cid)
                            if ctype: agent_connector_types.add(ctype)
                        for spec in ag_node.get("dataStoreSpecs", {}).get("specs", []):
                            ds = spec.get("dataStore", "").split("/")[-1]
                            if ds: agent_datastore_ids.add(ds)
                if wf_instructions:
                    system_instructions = "\n\n".join(wf_instructions)

            elif "skillAgentDefinition" in agent:
                agent_type = "Skill"
                sk = agent["skillAgentDefinition"]
                if "instruction" in sk: system_instructions = sk["instruction"]

            elif "managedAgentDefinition" in agent:
                agent_type = "Managed Agent"

            elif "a2aAgentDefinition" in agent:
                agent_type = "A2A Agent"

            # Derive connector info from datastores if not explicit
            for ds in agent_datastore_ids:
                m = re.match(r"^([a-zA-Z0-9\-]+_[0-9]+)_(.+)$", ds)
                if m:
                    cid = m.group(1)
                    agent_connector_ids.add(cid)
                    if not any(cid in x for x in agent_connector_types):
                        agent_connector_types.add(cid.split("_")[0].split("-")[0])

            sorted_ds = sorted(list(agent_datastore_ids))
            rows_to_insert.append({
                "agent_id": aid,
                "display_name": display_name,
                "engine_id": eng,
                "agent_type": agent_type,
                "description": description,
                "system_instructions": system_instructions,
                "datastore_ids": ",".join(sorted_ds),
                "datastore_names": ",".join([ds_lookup.get(ds, ds) for ds in sorted_ds]),
                "connector_ids": ",".join(sorted(list(agent_connector_ids))),
                "connector_types": ",".join(sorted(list(agent_connector_types))),
                "sub_agents": sub_agents_str
            })

    # 3. Upsert into BigQuery
    bq_client = bigquery.Client(project=project_id)
    table_ref = f"{project_id}.{dataset_id}.agent_names"
    
    if rows_to_insert:
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
            engine_id = S.engine_id,
            agent_type = S.agent_type,
            description = S.description,
            system_instructions = S.system_instructions,
            datastore_ids = S.datastore_ids,
            datastore_names = S.datastore_names,
            connector_ids = S.connector_ids,
            connector_types = S.connector_types,
            sub_agents = S.sub_agents
        WHEN NOT MATCHED THEN
          INSERT (agent_id, display_name, engine_id, agent_type, description, system_instructions, datastore_ids, datastore_names, connector_ids, connector_types, sub_agents)
          VALUES (S.agent_id, S.display_name, S.engine_id, S.agent_type, S.description, S.system_instructions, S.datastore_ids, S.datastore_names, S.connector_ids, S.connector_types, S.sub_agents);
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
                print(f"⚠️ Export skipped/failed for '{engine_id}': {res.status_code} - {res.text}")
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
        if not export_ok:
            raise RuntimeError(f"Failed to trigger metrics export on any engine. Details: {op_detail or 'None'}")
        
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

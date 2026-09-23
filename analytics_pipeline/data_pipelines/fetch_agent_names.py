import os
import sys
import time
import json
import re
import subprocess
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from google.auth import default
from google.auth.transport.requests import Request
from dotenv import load_dotenv

def get_auth_token():
    """Obtains access token via gcloud CLI first, falling back to ADC."""
    try:
        token = subprocess.check_output(
            ["gcloud", "auth", "print-access-token"], 
            stderr=subprocess.DEVNULL
        ).decode().strip()
        if token:
            return token
    except Exception:
        pass
    
    try:
        credentials, _ = default()
        credentials.refresh(Request())
        return credentials.token
    except Exception as e:
        print(f"❌ Failed to obtain Google Cloud credentials: {e}")
        sys.exit(1)

def create_http_session():
    """Creates a high-performance HTTP Session with connection pooling and keepalive."""
    session = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        raise_on_status=False
    )
    adapter = HTTPAdapter(
        pool_connections=50,
        pool_maxsize=50,
        max_retries=retries
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

def fetch_all_pages(session, base_url, headers, items_key):
    """Handles pagination for Discovery Engine list APIs using connection pooling."""
    results = []
    page_token = None
    params = {}
    while True:
        try:
            res = session.get(base_url, headers=headers, params=params, timeout=(10, 30))
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            print(f"⚠️ Network timeout connecting to {base_url}: {e}")
            break
        if res.status_code != 200:
            print(f"❌ Error fetching {base_url}: {res.status_code} - {res.text}")
            break
        data = res.json()
        results.extend(data.get(items_key, []))
        page_token = data.get("nextPageToken")
        if not page_token:
            break
        params["pageToken"] = page_token
    return results

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

def process_single_agent(session, headers, agt, engine_name, PROJECT_ID, LOCATION, ds_lookup):
    """Fetches details for a single agent and extracts agent-specific data stores and connectors."""
    raw_agt_name = agt.get("name", "")
    if not raw_agt_name:
        return None
        
    agent_id = str(raw_agt_name.split("/")[-1])
    display_name = agt.get("displayName", agt.get("draftDisplayName", "Unknown"))
    
    agt_details_url = f"https://discoveryengine.googleapis.com/v1alpha/{raw_agt_name}"
    description_string = ""
    system_instructions_string = ""
    sub_agents_str = ""
    agent_type = "Unknown"
    
    agent_datastore_ids = set()
    agent_connector_ids = set()
    agent_connector_types = set()
    
    try:
        agt_det_res = session.get(agt_details_url, headers=headers, timeout=(10, 20))
        if agt_det_res.status_code == 200:
            agt_data = agt_det_res.json()
            display_name = agt_data.get("displayName", agt_data.get("draftDisplayName", display_name))
            description_string = agt_data.get("description", agt_data.get("draftDescription", ""))
            
            if "adkAgentDefinition" in agt_data:
                agent_type = "ADK Agent"
            elif "lowCodeAgentDefinition" in agt_data:
                agent_type = "Agent Builder (UI)"
                builder_def = agt_data["lowCodeAgentDefinition"]
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
                            system_instructions_string = inst + "\n\n" + system_instructions_string
                        else:
                            sub_instructions.append(f"[{a.get('displayName', 'Sub-Agent')}] {inst}")
                            
                    # Extract data stores from low-code agent node
                    for spec in node.get("dataStoreSpecs", {}).get("specs", []):
                        ds = spec.get("dataStore", "").split("/")[-1]
                        if ds:
                            agent_datastore_ids.add(ds)

                    # Extract dataConnectors
                    for conn in node.get("dataConnectors", []):
                        cid, ctype = extract_connector_info(conn.get("name", ""), conn.get("dataSource"))
                        if cid: agent_connector_ids.add(cid)
                        if ctype: agent_connector_types.add(ctype)

                    # Extract connectorToolSelections
                    for sel in node.get("connectorToolSelections", []):
                        dc = sel.get("dataConnector", {})
                        cid, ctype = extract_connector_info(dc.get("name", ""), dc.get("dataSource"))
                        if cid: agent_connector_ids.add(cid)
                        if ctype: agent_connector_types.add(ctype)
                
                if sub_instructions:
                    system_instructions_string += "\nSub-Agent Instructions:\n" + "\n".join(sub_instructions)
                
                sub_agents_str = ", ".join(sub_agent_names)

            elif "workflowAgentDefinition" in agt_data:
                agent_type = "Workflow Agent"
                wf = agt_data["workflowAgentDefinition"]
                agent_flow = wf.get("agentFlow", {})
                flow_nodes = agent_flow.get("nodes", []) or wf.get("workflowDefinition", {}).get("nodes", [])
                
                wf_instructions = []
                for fn in flow_nodes:
                    # Check CONNECTOR_EVENT_TRIGGER
                    trig = fn.get("connectorEventTrigger", {})
                    if trig:
                        dc = trig.get("dataConnector", {})
                        cid, ctype = extract_connector_info(dc.get("name", ""), dc.get("dataSource"))
                        if cid: agent_connector_ids.add(cid)
                        if ctype: agent_connector_types.add(ctype)
                        for spec in trig.get("dataStoreSpecs", {}).get("specs", []):
                            ds = spec.get("dataStore", "").split("/")[-1]
                            if ds: agent_datastore_ids.add(ds)
                    
                    # Check AGENT_NODE
                    ag_node = fn.get("agentNode", {})
                    if ag_node:
                        inst = ag_node.get("instruction", "")
                        dname = fn.get("displayName", fn.get("id", "Agent Node"))
                        if inst:
                            wf_instructions.append(f"[{dname}] {inst}")
                        for sel in ag_node.get("connectorToolSelections", []):
                            dc = sel.get("dataConnector", {})
                            cid, ctype = extract_connector_info(dc.get("name", ""), dc.get("dataSource"))
                            if cid: agent_connector_ids.add(cid)
                            if ctype: agent_connector_types.add(ctype)
                        for spec in ag_node.get("dataStoreSpecs", {}).get("specs", []):
                            ds = spec.get("dataStore", "").split("/")[-1]
                            if ds: agent_datastore_ids.add(ds)

                if wf_instructions:
                    system_instructions_string = "\n\n".join(wf_instructions)

            elif "skillAgentDefinition" in agt_data:
                agent_type = "Skill"
                sk = agt_data["skillAgentDefinition"]
                if "instruction" in sk:
                    system_instructions_string = sk["instruction"]

            elif "managedAgentDefinition" in agt_data:
                agent_type = "Managed Agent"

            elif "a2aAgentDefinition" in agt_data:
                agent_type = "A2A Agent"
            
            if not system_instructions_string:
                instructions_obj = agt_data.get("instructions", {})
                sys_inst_list = instructions_obj.get("systemInstructions", [])
                extracted_prompts = [item.get("instruction", "") for item in sys_inst_list if item.get("instruction")]
                if extracted_prompts:
                    system_instructions_string = "\n".join(extracted_prompts)

            # Derive connector ID and type from datastores if not already explicitly captured
            for ds in agent_datastore_ids:
                m = re.match(r"^([a-zA-Z0-9\-]+_[0-9]+)_(.+)$", ds)
                if m:
                    cid = m.group(1)
                    agent_connector_ids.add(cid)
                    if not any(cid in x for x in agent_connector_types):
                        ctype = cid.split("_")[0].split("-")[0]
                        agent_connector_types.add(ctype)

    except Exception:
        # Fallback to list metadata if detail fetch fails
        pass

    engine_id_clean = engine_name.split("/")[-1] if engine_name else "default_engine"

    sorted_ds_ids = sorted(list(agent_datastore_ids))
    datastore_ids_str = ",".join(sorted_ds_ids)
    datastore_names_str = ",".join([ds_lookup.get(ds, ds) for ds in sorted_ds_ids])
    connector_ids_str = ",".join(sorted(list(agent_connector_ids)))
    connector_types_str = ",".join(sorted(list(agent_connector_types)))

    return {
        "agent_id": str(agent_id),
        "display_name": display_name,
        "engine_id": str(engine_id_clean),
        "description": description_string,
        "system_instructions": system_instructions_string,
        "datastore_ids": datastore_ids_str,
        "datastore_names": datastore_names_str,
        "connector_ids": connector_ids_str,
        "connector_types": connector_types_str,
        "agent_type": agent_type,
        "sub_agents": sub_agents_str
    }

def main():
    load_dotenv()
    PROJECT_ID = os.getenv("PROJECT_ID")
    LOCATION = os.getenv("GE_LOCATION", "global")
    DATASET_ID = os.getenv("DATASET_ID")

    BQ_LOCATION = os.getenv("BQ_LOCATION")

    if not PROJECT_ID or not DATASET_ID:
        print("❌ Error: PROJECT_ID or DATASET_ID missing in .env.")
        sys.exit(1)

    print("🔑 Obtaining Google Cloud authorization token...")
    TOKEN = get_auth_token()
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "x-goog-user-project": PROJECT_ID
    }
    
    session = create_http_session()

    print(f"📦 Pre-fetching collection data stores for display name resolution...")
    ds_lookup = {}
    try:
        ds_url = f"https://discoveryengine.googleapis.com/v1/projects/{PROJECT_ID}/locations/{LOCATION}/collections/default_collection/dataStores"
        data_stores = fetch_all_pages(session, ds_url, headers, "dataStores")
        for ds in data_stores:
            ds_id = ds.get("name", "").split("/")[-1]
            if ds_id:
                ds_lookup[ds_id] = ds.get("displayName", ds_id)
        print(f"  ✓ Cached {len(ds_lookup)} data stores.")
    except Exception as e:
        print(f"⚠️ Warning: Could not pre-fetch data stores: {e}")

    print(f"🔍 Discovering engines in project '{PROJECT_ID}' ({LOCATION})...")
    url = f"https://discoveryengine.googleapis.com/v1/projects/{PROJECT_ID}/locations/{LOCATION}/collections/default_collection/engines"
    engines = fetch_all_pages(session, url, headers, "engines")

    if not engines:
        print("ℹ️ No engines found in this project/location.")
        sys.exit(0)

    all_raw_agents = []

    for engine in engines:
        engine_name = engine.get("name")
        if not engine_name:
            continue

        # Fetch Assistants and raw Agents
        assistants_url = f"https://discoveryengine.googleapis.com/v1alpha/{engine_name}/assistants"
        assistants = fetch_all_pages(session, assistants_url, headers, "assistants")
        for ast in assistants:
            ast_name = ast.get("name")
            if not ast_name:
                continue
            agents_url = f"https://discoveryengine.googleapis.com/v1alpha/{ast_name}/agents"
            discovered = fetch_all_pages(session, agents_url, headers, "agents")
            for a in discovered:
                all_raw_agents.append((a, engine_name))

    total_agents = len(all_raw_agents)
    print(f"📊 Found {total_agents} total custom agents across {len(engines)} engines.")
    
    if total_agents == 0:
        print("ℹ️ No agents found to process.")
        sys.exit(0)

    # Parallel processing with connection pool
    workers = min(25, max(4, total_agents // 50))
    print(f"🚀 Fetching agent configurations concurrently using {workers} parallel keepalive workers...")

    records = []
    start_time = time.time()
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = []
        for agt, engine_name in all_raw_agents:
            futures.append(executor.submit(
                process_single_agent, session, headers, agt, engine_name, PROJECT_ID, LOCATION, ds_lookup
            ))

        completed = 0
        for future in as_completed(futures):
            res = future.result()
            if res:
                records.append(res)
            completed += 1
            if completed % 100 == 0 or completed == total_agents:
                elapsed = time.time() - start_time
                rate = completed / max(elapsed, 0.1)
                print(f"  ⚡ [{completed}/{total_agents}] agents processed ({rate:.1f} agents/sec)...")

    duration = time.time() - start_time
    print(f"✅ Fetched details for {len(records)} agents in {duration:.1f}s.")

    # Write to BigQuery (agent_names table)
    if records:
        print(f"🚀 Loading {len(records)} agent records into BigQuery: {PROJECT_ID}.{DATASET_ID}.agent_names...")
        
        # Ensure destination table exists and schema includes all expected columns
        schema_sql = f"""
        CREATE TABLE IF NOT EXISTS `{PROJECT_ID}.{DATASET_ID}.agent_names` (
          agent_id STRING,
          display_name STRING,
          engine_id STRING,
          description STRING,
          system_instructions STRING,
          datastore_ids STRING,
          datastore_names STRING,
          connector_ids STRING,
          connector_types STRING,
          agent_type STRING,
          sub_agents STRING
        );
        ALTER TABLE `{PROJECT_ID}.{DATASET_ID}.agent_names`
          ADD COLUMN IF NOT EXISTS engine_id STRING,
          ADD COLUMN IF NOT EXISTS system_instructions STRING,
          ADD COLUMN IF NOT EXISTS datastore_ids STRING,
          ADD COLUMN IF NOT EXISTS datastore_names STRING,
          ADD COLUMN IF NOT EXISTS sub_agents STRING,
          ADD COLUMN IF NOT EXISTS connector_ids STRING,
          ADD COLUMN IF NOT EXISTS connector_types STRING;
        """
        try:
            subprocess.run([
                "bq", "query",
                f"--project_id={PROJECT_ID}",
                "--use_legacy_sql=false",
                schema_sql
            ], capture_output=True, text=True, check=False)
        except Exception:
            pass

        temp_jsonl = f"/tmp/agent_names_{os.getpid()}.jsonl"
        with open(temp_jsonl, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec) + "\n")
                
        bq_cmd = [
            "bq", "load",
            f"--project_id={PROJECT_ID}",
            "--source_format=NEWLINE_DELIMITED_JSON",
            "--replace",
            "--autodetect",
        ]
        if BQ_LOCATION:
            bq_cmd.append(f"--location={BQ_LOCATION}")
        bq_cmd.extend([
            f"{PROJECT_ID}:{DATASET_ID}.agent_names",
            temp_jsonl
        ])

        try:
            res = subprocess.run(bq_cmd, capture_output=True, text=True)
            if res.returncode != 0:
                print(f"❌ BigQuery load failed with exit code {res.returncode}:")
                if res.stderr:
                    print(res.stderr.strip())
                if res.stdout:
                    print(res.stdout.strip())
                sys.exit(res.returncode)
            print(f"✅ Successfully updated {len(records)} Agent Name directory records in BigQuery.")
        finally:
            if os.path.exists(temp_jsonl):
                os.remove(temp_jsonl)

if __name__ == "__main__":
    main()
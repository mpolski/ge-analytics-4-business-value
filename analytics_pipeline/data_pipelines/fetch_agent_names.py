import os
import sys
import time
import json
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

def process_single_agent(session, headers, agt, engine_name, PROJECT_ID, LOCATION, datastore_ids_str, datastore_names_str):
    """Fetches details for a single agent."""
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
                
                if sub_instructions:
                    system_instructions_string += "\nSub-Agent Instructions:\n" + "\n".join(sub_instructions)
                
                sub_agents_str = ", ".join(sub_agent_names)
            elif "managedAgentDefinition" in agt_data:
                agent_type = "Managed Agent"
            
            if not system_instructions_string:
                instructions_obj = agt_data.get("instructions", {})
                sys_inst_list = instructions_obj.get("systemInstructions", [])
                extracted_prompts = [item.get("instruction", "") for item in sys_inst_list if item.get("instruction")]
                if extracted_prompts:
                    system_instructions_string = "\n".join(extracted_prompts)
    except Exception as e:
        # Fallback to list metadata if detail fetch fails
        pass

    engine_id_clean = engine_name.split("/")[-1] if engine_name else "default_engine"

    return {
        "agent_id": str(agent_id),
        "display_name": display_name,
        "engine_id": str(engine_id_clean),
        "description": description_string,
        "system_instructions": system_instructions_string,
        "datastore_ids": datastore_ids_str,
        "datastore_names": datastore_names_str,
        "agent_type": agent_type,
        "sub_agents": sub_agents_str
    }

def main():
    load_dotenv()
    PROJECT_ID = os.getenv("PROJECT_ID")
    LOCATION = os.getenv("GE_LOCATION", "global")
    DATASET_ID = os.getenv("DATASET_ID")

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

    print(f"🔍 Discovering engines in project '{PROJECT_ID}' ({LOCATION})...")
    url = f"https://discoveryengine.googleapis.com/v1/projects/{PROJECT_ID}/locations/{LOCATION}/collections/default_collection/engines"
    engines = fetch_all_pages(session, url, headers, "engines")

    if not engines:
        print("ℹ️ No engines found in this project/location.")
        sys.exit(0)

    all_raw_agents = []
    engine_contexts = {}

    for engine in engines:
        engine_name = engine.get("name")
        if not engine_name:
            continue
            
        # Fetch DataStores
        datastore_ids_str = ""
        datastore_names_str = ""
        try:
            eng_res = session.get(f"https://discoveryengine.googleapis.com/v1/{engine_name}", headers=headers, timeout=(10, 20))
            if eng_res.status_code == 200:
                data_store_ids = eng_res.json().get("dataStoreIds", [])
                datastore_ids_str = ",".join(data_store_ids)
                ds_names = []
                for ds_id in data_store_ids:
                    ds_url = f"https://discoveryengine.googleapis.com/v1/projects/{PROJECT_ID}/locations/{LOCATION}/collections/default_collection/dataStores/{ds_id}"
                    ds_res = session.get(ds_url, headers=headers, timeout=(10, 20))
                    ds_names.append(ds_res.json().get("displayName", ds_id) if ds_res.status_code == 200 else ds_id)
                datastore_names_str = ",".join(ds_names)
        except Exception:
            pass

        engine_contexts[engine_name] = (datastore_ids_str, datastore_names_str)

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
            ds_ids, ds_names = engine_contexts.get(engine_name, ("", ""))
            futures.append(executor.submit(
                process_single_agent, session, headers, agt, engine_name, PROJECT_ID, LOCATION, ds_ids, ds_names
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
        temp_jsonl = f"/tmp/agent_names_{os.getpid()}.jsonl"
        with open(temp_jsonl, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec) + "\n")
                
        subprocess.check_call([
            "bq", "load",
            f"--project_id={PROJECT_ID}",
            "--source_format=NEWLINE_DELIMITED_JSON",
            "--replace",
            f"{PROJECT_ID}:{DATASET_ID}.agent_names",
            temp_jsonl
        ])
        if os.path.exists(temp_jsonl):
            os.remove(temp_jsonl)
        print(f"✅ Successfully updated {len(records)} Agent Name directory records in BigQuery.")

if __name__ == "__main__":
    main()
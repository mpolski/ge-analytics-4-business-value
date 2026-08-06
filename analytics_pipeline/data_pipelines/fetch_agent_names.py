import os
import sys
import time
import subprocess
import requests
from google.auth import default
from google.auth.transport.requests import Request
from google.cloud import bigquery
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

def get_with_retry(url, headers, max_retries=5, initial_backoff=2):
    """Executes a GET request with exponential backoff for 429 and 5xx errors."""
    backoff = initial_backoff
    for attempt in range(1, max_retries + 1):
        res = requests.get(url, headers=headers)
        if res.status_code == 200:
            return res
        elif res.status_code in [429, 500, 503]:
            time.sleep(backoff)
            backoff *= 2
        else:
            return res
    return res

def fetch_all_pages(base_url, headers, items_key):
    """Handles pagination for Discovery Engine list APIs."""
    results = []
    page_token = None
    params = {}
    while True:
        res = requests.get(base_url, headers=headers, params=params)
        if res.status_code != 200:
            print(f"❌ Error fetching {base_url} after retries: {res.status_code} - {res.text}")
            break
        data = res.json()
        results.extend(data.get(items_key, []))
        page_token = data.get("nextPageToken")
        if not page_token:
            break
        params["pageToken"] = page_token
    return results

# 1. Load variables from .env
load_dotenv()
PROJECT_ID = os.getenv("PROJECT_ID")
LOCATION = os.getenv("GE_LOCATION", "global")
DATASET_ID = os.getenv("DATASET_ID")

if not PROJECT_ID:
    print("❌ Error: PROJECT_ID is not set. Please define PROJECT_ID in .env file.")
    sys.exit(1)

if not DATASET_ID:
    print("❌ Error: DATASET_ID is not set. Please define DATASET_ID in .env file.")
    sys.exit(1)

# 2. Get Authentication Token
print("🔑 Getting Google Cloud credentials...")
TOKEN = get_auth_token()

# 3. Fetch Agents (Engines) from the API
url = f"https://discoveryengine.googleapis.com/v1/projects/{PROJECT_ID}/locations/{LOCATION}/collections/default_collection/engines"
headers = {
    "Authorization": f"Bearer {TOKEN}",
    "x-goog-user-project": PROJECT_ID
}

print(f"🔍 Fetching Agent Names from Vertex AI...")
engines = fetch_all_pages(url, headers, "engines")

if not engines:
    print("⚠️ No engines found in this project/location.")
    exit(0)

# 4. Fetch Assistants and Agents for each Engine
records = []
for engine in engines:
    engine_name = engine.get("name")
    if not engine_name:
        continue
        
    # A. Fetch Engine DataStores
    engine_details_url = f"https://discoveryengine.googleapis.com/v1/{engine_name}"
    eng_res = get_with_retry(engine_details_url, headers=headers)
    datastore_ids_str = ""
    datastore_names_str = ""
    
    if eng_res.status_code == 200:
        eng_data = eng_res.json()
        data_store_ids = eng_data.get("dataStoreIds", [])
        datastore_ids_str = ",".join(data_store_ids)
        
        # B. Fetch DataStore Names
        ds_names = []
        for ds_id in data_store_ids:
            ds_url = f"https://discoveryengine.googleapis.com/v1/projects/{PROJECT_ID}/locations/{LOCATION}/collections/default_collection/dataStores/{ds_id}"
            ds_res = get_with_retry(ds_url, headers=headers)
            if ds_res.status_code == 200:
                ds_names.append(ds_res.json().get("displayName", ds_id))
            else:
                ds_names.append(ds_id)
        datastore_names_str = ",".join(ds_names)

    # Fetch Assistants
    assistants_url = f"https://discoveryengine.googleapis.com/v1alpha/{engine_name}/assistants"
    assistants = fetch_all_pages(assistants_url, headers, "assistants")
    for ast in assistants:
        ast_name = ast.get("name")
        if not ast_name:
            continue
            
        # Fetch Agents
        agents_url = f"https://discoveryengine.googleapis.com/v1alpha/{ast_name}/agents"
        agents = fetch_all_pages(agents_url, headers, "agents")
        for agt in agents:
            raw_agt_name = agt.get("name", "")
            if not raw_agt_name:
                continue
            agent_id = str(raw_agt_name.split("/")[-1])
            display_name = agt.get("displayName", agt.get("draftDisplayName", "Unknown"))
            print(f"🔍 Discovered Agent: '{display_name}' (ID: {agent_id})")
            
            # C. Fetch Agent Details
            agt_details_url = f"https://discoveryengine.googleapis.com/v1alpha/{raw_agt_name}"
            agt_det_res = get_with_retry(agt_details_url, headers=headers)
            
            description_string = ""
            system_instructions_string = ""
            sub_agents_str = ""
            agent_type = "Unknown"
            
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
                
                # Single prompt fallback
                if not system_instructions_string:
                    instructions_obj = agt_data.get("instructions", {})
                    sys_inst_list = instructions_obj.get("systemInstructions", [])
                    extracted_prompts = [item.get("instruction", "") for item in sys_inst_list if item.get("instruction")]
                    if extracted_prompts:
                        system_instructions_string = "\n".join(extracted_prompts)
                        
            records.append({
                "agent_id": str(agent_id),
                "display_name": display_name,
                "description": description_string,
                "system_instructions": system_instructions_string,
                "datastore_ids": datastore_ids_str,
                "datastore_names": datastore_names_str,
                "agent_type": agent_type,
                "sub_agents": sub_agents_str
            })

# 5. Write to BigQuery (agent_names table)
if records:
    import json
    print(f"🚀 Loading {len(records)} Agent Name records into BigQuery table: {PROJECT_ID}.{DATASET_ID}.agent_names...")
    temp_jsonl = f"/tmp/agent_names_{os.getpid()}.jsonl"
    with open(temp_jsonl, "w") as f:
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
    print(f"✅ Loaded {len(records)} Agent Name records successfully.")
else:
    print("ℹ️ No agents found to save.")
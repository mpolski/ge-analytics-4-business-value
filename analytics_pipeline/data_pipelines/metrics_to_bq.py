import os
import sys
import json
import time
import subprocess
import requests
import google.auth
import google.auth.transport.requests
from dotenv import load_dotenv

def export_metrics():
    # 1. Load the variables from the .env file
    load_dotenv()
    
    project_id = os.getenv("PROJECT_ID")
    location = os.getenv("GE_LOCATION") or os.getenv("LOCATION", "global")
    dataset_id = os.getenv("DATASET_ID")
    table_id = "agent_session_metrics"
    
    if not project_id:
        print("❌ Error: PROJECT_ID is not set. Please define PROJECT_ID in .env file.")
        sys.exit(1)
    if not dataset_id:
        print("❌ Error: DATASET_ID is not set. Please define DATASET_ID in .env file.")
        sys.exit(1)

    # 2. Authenticate using active gcloud session or ADC
    token = None
    try:
        token = subprocess.check_output(
            ["gcloud", "auth", "print-access-token"], 
            stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        pass
        
    if not token:
        try:
            credentials, _ = google.auth.default(
                scopes=['https://www.googleapis.com/auth/cloud-platform']
            )
            auth_req = google.auth.transport.requests.Request()
            credentials.refresh(auth_req)
            token = credentials.token
        except Exception as e:
            print(f"❌ Auth failed. Run 'gcloud auth application-default login' first.\nError: {e}")
            sys.exit(1)
            
    # 3. Parse target engines (supports comma-separated list or auto-discovery)
    engine_input = os.getenv("ENGINE_ID", "").strip()
    target_engines = []
    
    if engine_input and engine_input.upper() not in ["ALL", "AUTO", "*"]:
        target_engines = [e.strip() for e in engine_input.split(",") if e.strip()]
    else:
        # Auto-discover all engines in project/location
        print(f"🔍 Auto-discovering all engines in project '{project_id}'...")
        list_url = f"https://discoveryengine.googleapis.com/v1/projects/{project_id}/locations/{location}/collections/default_collection/engines"
        auth_headers = {'Authorization': f'Bearer {token}', 'x-goog-user-project': project_id}
        try:
            l_res = requests.get(list_url, headers=auth_headers, timeout=(10, 20))
            if l_res.status_code == 200:
                engines_list = l_res.json().get("engines", [])
                target_engines = [e.get("name", "").split("/")[-1] for e in engines_list if e.get("name")]
        except Exception as e:
            print(f"⚠️ Auto-discovery failed: {e}")
            
    if not target_engines:
        print("❌ Error: No engines found to export. Set ENGINE_ID in .env (e.g. ENGINE_ID=engine-1,engine-2).")
        sys.exit(1)
        
    print(f"🚀 Triggering metrics export across {len(target_engines)} engine(s): {', '.join(target_engines)}")
    print(f"📁 Destination Table: {project_id}.{dataset_id}.{table_id}")

    # 2. Iterate through each engine and trigger exportMetrics
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
        'x-goog-user-project': project_id
    }
    payload = {
        "outputConfig": {
            "bigqueryDestination": {
                "datasetId": dataset_id,
                "tableId": table_id
            }
        }
    }
    
    successful_ops = []
    
    for idx, engine_id in enumerate(target_engines, 1):
        print(f"\n📦 [{idx}/{len(target_engines)}] Triggering export for Engine: '{engine_id}'...")
        url = f"https://discoveryengine.googleapis.com/v1alpha/projects/{project_id}/locations/{location}/collections/default_collection/engines/{engine_id}/analytics:exportMetrics"
        try:
            response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=(10, 30))
            if response.status_code == 200:
                operation_name = response.json().get('name')
                successful_ops.append(operation_name)
                print(f"  ✅ Triggered successfully! Operation: {operation_name}")
            else:
                print(f"  ⚠️ Warning: Export failed for {engine_id}: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"  ⚠️ Exception exporting for {engine_id}: {e}")
    
    if successful_ops:
        print(f"\n✅ Successfully triggered export across {len(successful_ops)} engine(s).")
        # Poll the last operation for completion
        last_op = successful_ops[-1]
        poll_url = f"https://discoveryengine.googleapis.com/v1alpha/{last_op}"
        print(f"⏳ Waiting for export job to complete ({last_op.split('/')[-1]})...")
        
        for _ in range(30):
            try:
                poll_resp = requests.get(poll_url, headers=headers, timeout=(10, 20))
                if poll_resp.status_code == 200:
                    poll_data = poll_resp.json()
                    if poll_data.get("done"):
                        if "error" in poll_data:
                            print(f"\n❌ Export operation reported error: {poll_data['error']}")
                        else:
                            print("\n🎉 Export completed successfully!")
                        break
            except Exception:
                pass
            
            time.sleep(5)
            print(".", end="", flush=True)
        print("")
    else:
        print("❌ Error: No export operations succeeded.")
        sys.exit(1)

if __name__ == "__main__":
    export_metrics()
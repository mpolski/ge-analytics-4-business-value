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
    
    # 1. Parse target engines (supports comma-separated list or auto-discovery)
    engine_input = os.getenv("ENGINE_ID", "").strip()
    target_engines = []
    
    if engine_input and engine_input.upper() not in ["ALL", "AUTO", "*"]:
        # Comma-separated list or single ID (e.g., "engine-1,engine-2")
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
    
    for idx, engine_id in enumerate(target_engines, 1):
        print(f"\n📦 [{idx}/{len(target_engines)}] Triggering export for Engine: '{engine_id}'...")
        url = f"https://discoveryengine.googleapis.com/v1alpha/projects/{project_id}/locations/{location}/collections/default_collection/engines/{engine_id}/analytics:exportMetrics"
        response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=(10, 30))
        
        if response.status_code == 200:
            operation_name = response.json().get('name')
            print(f"  ✅ Triggered successfully! Operation: {operation_name}")
        else:
            print(f"  ⚠️ Warning: Export failed for {engine_id}: {response.status_code} - {response.text}")
    
    if response.status_code == 200:
        operation_name = response.json().get('name')
        print(f"✅ Success! Google is processing the export.")
        print(f"🔍 Operation ID: {operation_name}")
        
        # Poll for completion
        poll_url = f"https://discoveryengine.googleapis.com/v1alpha/{operation_name}"
        print("⏳ Waiting for export job to complete...")
        
        while True:
            poll_resp = requests.get(poll_url, headers=headers)
            if poll_resp.status_code == 200:
                poll_data = poll_resp.json()
                if poll_data.get("done"):
                    if "error" in poll_data:
                        print(f"❌ Export failed: {poll_data['error']}")
                        sys.exit(1)
                    else:
                        print("🎉 Export completed successfully!")
                        break
            else:
                print(f"⚠️ Failed to check operation status: {poll_resp.status_code}")
            
            time.sleep(10)
            print(".", end="", flush=True)
            
    else:
        print(f"❌ Error {response.status_code}: {response.text}")

if __name__ == "__main__":
    export_metrics()
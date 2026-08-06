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
    engine_id = os.getenv("ENGINE_ID")
    dataset_id = os.getenv("DATASET_ID")
    table_id = "agent_session_metrics"
    
    # Safety check
    if not project_id:
        print("❌ Error: PROJECT_ID is not set. Please define PROJECT_ID in .env file.")
        sys.exit(1)
    if not engine_id:
        print("❌ Error: ENGINE_ID is not set. Please define ENGINE_ID in .env file.")
        sys.exit(1)
    if not dataset_id:
        print("❌ Error: DATASET_ID is not set. Please define DATASET_ID in .env file.")
        sys.exit(1)
        
    print(f"🚀 Triggering export for Engine: {engine_id}")
    print(f"📁 Destination: {project_id}.{dataset_id}.{table_id}")

    # 2. Authenticate using your active gcloud session or ADC
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

    # 3. Build the API Request
    url = f"https://discoveryengine.googleapis.com/v1alpha/projects/{project_id}/locations/{location}/collections/default_collection/engines/{engine_id}/analytics:exportMetrics"
    
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
        'x-goog-user-project': project_id
    }
    
    # Note: Cross-project export is NOT supported by the discoveryengine API payload.
    # The datasetId must be in the same project as the Engine.
    payload = {
        "outputConfig": {
            "bigqueryDestination": {
                "datasetId": dataset_id,
                "tableId": table_id
            }
        }
    }
    # 4. Fire the Request
    response = requests.post(url, headers=headers, data=json.dumps(payload))
    
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
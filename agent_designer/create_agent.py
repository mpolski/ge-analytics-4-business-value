import os
import sys
import subprocess
import requests
from dotenv import load_dotenv

def create_ge_agent():
    # 1. Load variables from .env
    env_path = os.path.join(os.path.dirname(__file__), '..', 'analytics_pipeline', '.env')
    load_dotenv(env_path)
    
    project_id = os.getenv("PROJECT_ID")
    engine_id = os.getenv("ENGINE_ID")
    location = os.getenv("GE_LOCATION", "global")
    dataset_id = os.getenv("DATASET_ID", "ge_metrics")
    
    if not project_id or not engine_id:
        print("❌ Error: PROJECT_ID or ENGINE_ID not set in analytics_pipeline/.env")
        sys.exit(1)
        
    print(f"🚀 Preparing to create Agent in Project: {project_id}")

    # 2. Read Instructions and Substitute Variables
    instructions_path = os.path.join(os.path.dirname(__file__), 'instructions.md')
    if not os.path.exists(instructions_path):
        print("❌ Error: instructions.md not found.")
        sys.exit(1)
        
    with open(instructions_path, 'r') as f:
        instructions_content = f.read()
        
    knowledge_path = os.path.join(os.path.dirname(__file__), 'knowledge.md')
    if os.path.exists(knowledge_path):
        with open(knowledge_path, 'r') as f:
            knowledge_content = f.read()
        instructions_content += "\n\n---\n\n### KNOWLEDGE BASE (Reference Material):\n\n" + knowledge_content
        
    # Replace placeholders
    instructions_content = instructions_content.replace("<your_project_id>", project_id)
    instructions_content = instructions_content.replace("<your_dataset_id>", dataset_id)
    
    # 3. Get Auth Token
    try:
        token = subprocess.check_output(["gcloud", "auth", "print-access-token"], stderr=subprocess.DEVNULL).decode().strip()
    except Exception as e:
        print("❌ Failed to obtain Google Cloud token. Run 'gcloud auth login' first.")
        sys.exit(1)

    # 4. Define the Agent Payload
    payload = {
        "displayName": "GE App Business Value",
        "description": "Provides reporting on GE App utilization, top agents, features used by users.",
        "state": "ENABLED",
        "sharingConfig": {
            "scope": "ALL_USERS"
        },
        "lowCodeAgentDefinition": {
            "draftDisplayName": "GE App Business Value",
            "draftDescription": "Provides reporting on GE App utilization, top agents, features used by users.",
            "draftStarterPrompts": [
                { "text": "What can you help me with?" },
                { "text": "Show me our top agent creators." },
                { "text": "What is our daily active user trend for this month?" },
                { "text": "Show me a summary of feature adoption percentages for this week." }
            ],
            "rootAgentId": "root_agent",
            "nodes": [
                {
                    "id": "root_agent",
                    "displayName": "GE App Business Value",
                    "llmAgentNode": {
                        "model": "gemini-3.5-flash",
                        "instruction": instructions_content,
                        "dataStoreSpecs": {
                            "specs": []
                        }
                    }
                }
            ],
            "deployedNodes": [
                {
                    "id": "root_agent",
                    "displayName": "GE App Business Value",
                    "llmAgentNode": {
                        "model": "gemini-3.5-flash",
                        "instruction": instructions_content,
                        "dataStoreSpecs": {
                            "specs": []
                        }
                    }
                }
            ],
            "deployedRootAgentId": "root_agent"
        }
    }

    # 5. Execute API Call
    url = f"https://discoveryengine.googleapis.com/v1alpha/projects/{project_id}/locations/{location}/collections/default_collection/engines/{engine_id}/assistants/default_assistant/agents"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "x-goog-user-project": project_id
    }
    
    print("📡 Sending CreateAgent API request...")
    res = requests.post(url, headers=headers, json=payload)
    
    if res.status_code == 200:
        data = res.json()
        agent_name = data.get("name")
        print("✅ Successfully created Agent!")
        print(f"🔍 Agent Resource Name: {agent_name}")
        print("\n---------------------------------------------------------")
        print("💡 The knowledge base has been successfully embedded directly into the agent's instructions!")
        print("---------------------------------------------------------")
    else:
        print(f"❌ Error creating agent: {res.status_code}")
        print(res.text)

if __name__ == "__main__":
    create_ge_agent()

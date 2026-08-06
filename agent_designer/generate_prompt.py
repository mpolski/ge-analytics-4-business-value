#!/usr/bin/env python3
import os
import sys
from dotenv import load_dotenv

def generate_prompt():
    # 1. Load variables from .env
    base_dir = os.path.dirname(__file__)
    env_path = os.path.join(base_dir, '..', 'analytics_pipeline', '.env')
    
    if os.path.exists(env_path):
        load_dotenv(env_path)
    else:
        print(f"⚠️ Warning: .env file not found at {env_path}, using defaults/environment variables.")

    project_id = os.getenv("PROJECT_ID", "genai-ge-app")
    dataset_id = os.getenv("DATASET_ID", "ge_metrics")

    print(f"🔍 Generating prompt with:")
    print(f"   • Project ID: {project_id}")
    print(f"   • Dataset ID: {dataset_id}")

    # 2. Read instructions.md template
    instructions_path = os.path.join(base_dir, 'instructions.md')
    if not os.path.exists(instructions_path):
        print(f"❌ Error: {instructions_path} not found.")
        sys.exit(1)

    with open(instructions_path, 'r', encoding='utf-8') as f:
        prompt_content = f.read()

    # 3. Read knowledge.md and append
    knowledge_path = os.path.join(base_dir, 'knowledge.md')
    if os.path.exists(knowledge_path):
        with open(knowledge_path, 'r', encoding='utf-8') as f:
            knowledge_content = f.read()
        prompt_content += "\n\n---\n\n### KNOWLEDGE BASE (Reference Material):\n\n" + knowledge_content
        print("   • Knowledge Base (knowledge.md): Embedded successfully.")

    # 4. Substitute placeholders
    prompt_content = prompt_content.replace("<your_project_id>", project_id)
    prompt_content = prompt_content.replace("<your_dataset_id>", dataset_id)

    # 5. Write to prompt.md
    output_path = os.path.join(base_dir, 'prompt.md')
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(prompt_content)

    print(f"\n🎉 Successfully generated: {output_path}")
    print("📋 You can now copy and paste the contents of 'prompt.md' directly into the Instructions field in Agent Designer!")

if __name__ == "__main__":
    generate_prompt()

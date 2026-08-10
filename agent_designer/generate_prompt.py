#!/usr/bin/env python3
import os
import sys
from pathlib import Path

def load_env(env_path: Path) -> dict:
    env_vars = {}
    if env_path.exists():
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    env_vars[k.strip()] = v.strip().strip('"').strip("'")
    return env_vars

def generate_prompt():
    script_dir = Path(__file__).parent.resolve()
    repo_root = script_dir.parent.resolve()
    
    # 1. Locate .env
    env_candidates = [
        repo_root / "analytics_pipeline" / ".env",
        repo_root / ".env",
        script_dir / ".env"
    ]
    env_file = next((p for p in env_candidates if p.exists()), None)
    env_vars = load_env(env_file) if env_file else {}
    
    project_id = env_vars.get("PROJECT_ID", os.getenv("PROJECT_ID", "genai-ge-app"))
    dataset_id = env_vars.get("DATASET_ID", os.getenv("DATASET_ID", "ge_metrics"))

    print(f"🔍 Generating prompt with:")
    print(f"   • Project ID: {project_id}")
    print(f"   • Dataset ID: {dataset_id}")

    # 2. Read instructions.md template
    instructions_path = script_dir / "instructions.md"
    if not instructions_path.exists():
        print(f"❌ Error: {instructions_path} not found.")
        sys.exit(1)

    prompt_content = instructions_path.read_text(encoding='utf-8')

    # 3. Read knowledge.md and append
    knowledge_path = script_dir / "knowledge.md"
    if knowledge_path.exists():
        knowledge_content = knowledge_path.read_text(encoding='utf-8')
        prompt_content += "\n\n---\n\n### KNOWLEDGE BASE (Reference Material):\n\n" + knowledge_content
        print("   • Knowledge Base (knowledge.md): Embedded successfully.")

    # 4. Substitute placeholders
    prompt_content = prompt_content.replace("<your_project_id>", project_id)
    prompt_content = prompt_content.replace("<your_dataset_id>", dataset_id)

    # 5. Write to prompt.md
    output_path = script_dir / "prompt.md"
    output_path.write_text(prompt_content, encoding='utf-8')

    print(f"\n🎉 Successfully generated: {output_path}")
    print("📋 You can now copy and paste the contents of 'prompt.md' directly into the Instructions field in Agent Designer!")

if __name__ == "__main__":
    generate_prompt()

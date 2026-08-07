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

def main():
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
    
    project_id = env_vars.get("PROJECT_ID", os.getenv("PROJECT_ID", "your-project-id"))
    dataset_id = env_vars.get("DATASET_ID", os.getenv("DATASET_ID", "ge_metrics"))
    
    print(f"🔧 Generating BigQuery Data Agent Prompt for Project: '{project_id}', Dataset: '{dataset_id}'")
    
    # 2. Read instructions and knowledge
    instructions_file = script_dir / "instructions.md"
    knowledge_file = repo_root / "agent_designer" / "knowledge.md"
    
    if not instructions_file.exists():
        print(f"❌ Error: {instructions_file} not found.")
        sys.exit(1)
        
    instructions_content = instructions_file.read_text(encoding='utf-8')
    knowledge_content = knowledge_file.read_text(encoding='utf-8') if knowledge_file.exists() else ""
    
    # 3. Perform substitutions
    instructions_resolved = instructions_content.replace("{{PROJECT_ID}}", project_id).replace("{{DATASET_ID}}", dataset_id)
    
    full_prompt = f"""{instructions_resolved}

---

## 📚 Reference Knowledge Base & Capabilities

{knowledge_content}
"""
    
    output_file = script_dir / "prompt.md"
    output_file.write_text(full_prompt, encoding='utf-8')
    print(f"✅ Generated BigQuery Agent Prompt: {output_file}")

if __name__ == "__main__":
    main()

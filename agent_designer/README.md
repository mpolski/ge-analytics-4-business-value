# Agent Designer Instructions

This directory contains the configuration instructions and tools for deploying the Gemini Enterprise Analytics & Business Value agent.

## Quick Start (Generate Prompt)

We provide a Python script that automatically reads your `.env` configuration (Project ID, Dataset ID, etc.), fills in all table and view names, and bundles the knowledge base into a single file called `prompt.md`.

1. **Generate the customized prompt:**
   ```bash
   uv run python agent_designer/generate_prompt.py
   ```
2. **Open the generated `prompt.md`:**
   Copy the entire contents of [prompt.md](prompt.md).
3. **Paste into Agent Designer:**
   Open the **Gemini Enterprise Console**, create or edit your agent in **Agent Designer**, and paste the copied text directly into the **Instructions** field.

## Sample Queries (Conversation Starters)

When setting up your agent, you can add these sample questions as "Conversation Starters" to guide users on what they can ask:

1. *"What is our daily active user trend for this month?"*
2. *"Show me our top 5 agent creators and the agents they've built."*
3. *"What is the feature adoption breakdown between Chat, NotebookLM, and Agents for this week?"*

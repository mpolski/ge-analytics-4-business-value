# Agent Designer Instructions & Deployment Guide

This directory contains the instructions, templates, and tools for deploying the **Business Value & Analytics Agent** in Gemini Enterprise (GE) Agent Designer.

---

## 🛠️ Step 1: Generate the Customized System Prompt

The prompt generator reads your environment parameters (`PROJECT_ID`, `DATASET_ID`) from `analytics_pipeline/.env`, dynamically populates [`instructions_template.md`](instructions_template.md), embeds the reference material from [`knowledge.md`](knowledge.md), and bundles everything into [`prompt.md`](prompt.md):

```bash
python3 agent_designer/generate_prompt.py
```

---

## 🤖 Step 2: Configure the Agent in Agent Designer

In the Google Cloud Console, navigate to **Gemini Enterprise** > **Agent Designer** (or **Agents** > **Create Agent**) and configure the following parameters:

| Configuration Field | Recommended Value |
| :--- | :--- |
| **Agent Name** | **`Business Value Agent`** *(or `GE Business Value Agent`)* |
| **Description** | `Provides executive reporting, adoption trends, feature usage analysis (Chat Assistant, NotebookLM vs. Agents), agent performance leaderboards, and creator governance across Gemini Enterprise.` |
| **Instructions / System Prompt** | Copy and paste the entire contents of the generated [`prompt.md`](prompt.md) |
| **Tools / Data Store** | Attach your BigQuery Data Store (e.g., `ge-metrics-bigquery-store`) with `execute_sql_readonly`, `describe_table`, and `list_tables` enabled. |

---

## 💬 Step 3: Add Conversation Starters (Sample Prompts)

Add these sample questions as **Conversation Starters** in the agent configuration to guide business users and executives on what they can ask:

1. *"What can you help me with?"*
2. *"What is our daily active user trend for this month?"*
3. *"Show me our top 5 agent creators and the agents they've built."*
4. *"What is the feature adoption breakdown between Chat, NotebookLM, and Agents for this week?"*
5. *"Which custom agents are most popular ranked by total interaction volume?"*
6. *"Show me power users who interact with all 3 features (Chat, NotebookLM, and Agents)."*

---

## ⚡ Optional: Programmatic Agent Creation via API

If you prefer to deploy the agent programmatically via the Discovery Engine REST API instead of the UI, run:

```bash
python3 agent_designer/create_agent.py
```
*(Requires `roles/discoveryengine.editor` permissions and an active gcloud session).*

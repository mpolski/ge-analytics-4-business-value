# BigQuery Native Data Agent & A2A Integration

A direct, table-based conversational AI agent configured in **BigQuery Studio / Vertex AI Agents** and integrated into **Gemini Enterprise (GE) App** via **Agent-to-Agent (A2A)** protocol.

---

## 💡 Why Use This Architecture?

* **Zero Organization Policy Constraints:** Bypasses custom MCP connector constraints (`constraints/discoveryengine.managed.disableCustomMcpServerConnector`) for organizations with strict enterprise security policies.
* **Direct Table Querying:** Queries the 4 base storage tables directly, bypassing view indexing limitations.
* **Enterprise A2A Protocol:** Once published in Google Cloud, the agent is registered directly in Gemini Enterprise App as an **A2A Agent** without requiring third-party server hosting.

---

## 🏛️ Target Base Tables

The agent is pre-configured to execute precise SQL against the 4 core storage tables:

1. **`discoveryengine_googleapis_com_gemini_enterprise_user_activity`**: Real-time turn-by-turn chat and custom agent interaction logs.
2. **`discoveryengine_googleapis_com_notebooklm_enterprise_user_activity`**: Real-time turn-by-turn NotebookLM Enterprise user telemetry.
3. **`agent_names`**: Persistent agent lookup directory mapping numeric IDs to display names, system instructions, and architecture.
4. **`historical_creators`**: Audit log records mapping agent IDs to creator email addresses and creation timestamps.

---

## 🚀 Step-by-Step Deployment Guide

### Step 1: Generate the Tailored Prompt

Run the prompt generator to automatically resolve your `.env` project parameters and produce `prompt.md`:

```bash
cd bq_agent
python3 generate_prompt.py
```

---

### Step 2: Create the Agent in Google Cloud

1. In the Google Cloud Console, navigate to **BigQuery** > **Studio** (or **Vertex AI** > **Agents**).
2. Click **Create Agent** > Select **Data Agent (SQL / BigQuery)**.
3. Assign a name: **`GE App Business Value (BigQuery)`**.
4. Attach the 4 base storage tables from your analytics dataset (`ge_metrics`):
   * `discoveryengine_googleapis_com_gemini_enterprise_user_activity`
   * `discoveryengine_googleapis_com_notebooklm_enterprise_user_activity`
   * `agent_names`
   * `historical_creators`
5. Open [`prompt.md`](prompt.md), copy its entire contents, and paste them into the agent's **Instructions / System Prompt** field.
6. Save and test the agent in the preview panel.

---

### Step 3: Publish & Register as an A2A Agent in Gemini Enterprise

1. In Vertex AI Agent Builder, click **Publish** on your BigQuery Data Agent.
2. Navigate to **Gemini Enterprise** > **Agents & Apps** > **Agents**.
3. Click **Register Agent** > Select **A2A Agent (Agent-to-Agent)**.
4. Select your published BigQuery agent from the list.
5. Provide a description (e.g., *"Answers questions about Gemini Enterprise usage, user adoption, NotebookLM metrics, agent leaderboards, and creator governance"*).
6. Click **Save & Activate**.

---

## 💬 Sample Queries to Test

Once registered, your enterprise users can ask the agent natural language questions directly in the Gemini Enterprise App chat:

* *"What is our overall Daily Active User (DAU) trend and feature adoption breakdown for this month?"*
* *"Show me the breakdown between users who only use Chat versus users who use NotebookLM and Custom Agents."*
* *"Which custom agents have had the highest interaction volume?"*
* *"Who created the 'Document Summary & Analysis' agent and when was it created?"*
* *"List all corporate employees who have interacted with all three features (Chat, NotebookLM, and Agents)."*

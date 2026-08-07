# BigQuery Native Data Agent & Gemini Enterprise A2A Integration

A direct, table-based conversational AI analytics agent configured in **BigQuery Studio / Gemini Data Analytics** and integrated into **Gemini Enterprise (GE) App** via the **Agent-to-Agent (A2A)** protocol.

---

## 💡 Why Use This Architecture?

* **Zero Organization Policy Constraints:** Bypasses custom MCP connector restrictions (`constraints/discoveryengine.managed.disableCustomMcpServerConnector`) for enterprises with strict security baselines.
* **Direct Table Querying:** Queries the 5 base storage tables directly, bypassing view indexing limitations.
* **Enterprise A2A Protocol:** Fully native Google Cloud communication between Gemini Enterprise and BigQuery under end-user delegated OAuth 2.0 authorization.
* **Executive-Ready Presentation:** Structured to return clean Markdown tables and text-based bar charts rather than echoing raw SQL code.

---

## 🏛️ Core Data Storage Tables

When building the agent in BigQuery Studio, select the **5 Core Data tables** from your analytics dataset (`ge_metrics`):

1. **`discoveryengine_googleapis_com_gemini_enterprise_user_activity`**: Real-time conversational turns with Gemini Enterprise Assistant (general chat) and custom agents.
2. **`discoveryengine_googleapis_com_notebooklm_enterprise_user_activity`**: Real-time turn interactions and document actions in NotebookLM Enterprise.
3. **`agent_names`**: Persistent directory mapping opaque numeric agent IDs to display names, system prompts, data stores, and architectures (`ADK` vs `UI`).
4. **`historical_creators`**: Audit trail mapping custom agent IDs to creator email addresses, creation timestamps, and engine IDs.
5. **`agent_session_metrics`**: Native Discovery Engine periodic session volume and monthly active user (MAU) aggregates.

*(Note: Skip `cloudaudit_googleapis_com_data_access`, `export_errors`, and SQL views `vw_*` as the agent queries the 5 Core Data tables directly).*

---

## 🚀 Step-by-Step Deployment Guide

### Step 1: Generate the Tailored System Prompt

Run the prompt generator to automatically inject your `.env` project parameters into `bq_agent/prompt.md`:

```bash
cd bq_agent
python3 generate_prompt.py
```

---

### Step 2: Create & Publish the Data Agent in BigQuery Studio

1. In the [Google Cloud Console](https://console.cloud.google.com), open **BigQuery** > **Studio** > **Data Agents** (or **Gemini Data Analytics**).
2. Click **Create Agent** > Select **Data Agent (SQL / BigQuery)**.
3. Assign a Name: **`GE Analytics`**.
   > 📌 **Note on Agent Naming:** The name you assign to the agent here in BigQuery Studio (e.g., **`GE Analytics`**) will automatically become the official name of the agent displayed to end users in the Gemini Enterprise App.
4. Under **Data Sources / Knowledge Sources (Tables to Query)**, click **Add Tables**:
   * Use the **Filter tables** box to search for your dataset (`ge_metrics`).
   * **Check the 5 Core Data tables**:
     * ✅ `discoveryengine_googleapis_com_gemini_enterprise_user_activity`
     * ✅ `discoveryengine_googleapis_com_notebooklm_enterprise_user_activity`
     * ✅ `agent_names`
     * ✅ `historical_creators`
     * ✅ `agent_session_metrics`
5. Open [`bq_agent/prompt.md`](prompt.md), copy the entire text, and paste it into the agent's **Instructions / System Prompt** field.
6. Click **Save** and test the agent in the preview panel.
7. Click **Publish** > Click **Download JSON** to download the official Google **A2A Agent Card JSON**.

---

### Step 3: Create the OAuth 2.0 Credentials in Google Cloud

To enable Gemini Enterprise to securely query BigQuery under the end-user's Google account:

#### A. Configure the OAuth Consent Screen (Branding)
1. Go to **APIs & Services** > **[OAuth consent screen](https://console.cloud.google.com/apis/credentials/consent)**.
2. Under **App name**, enter a clean, enterprise title (e.g. **`Gemini Enterprise Connectors`** or **`[Company] AI Connectors`**).
   *(Avoid raw engine IDs so employees see a familiar, trusted enterprise name).*
3. Set your User support email and Developer contact email, then click **Save and Continue**.

#### B. Create the OAuth 2.0 Client ID
1. Go to **APIs & Services** > **[Credentials](https://console.cloud.google.com/apis/credentials)**.
2. Click **+ Create Credentials** > **OAuth client ID**.
3. Application type: **Web application**.
4. Name: `Gemini Enterprise A2A Connector`.
5. Under **Authorized redirect URIs**, click **+ Add URI** and add BOTH:
   * `https://vertexaisearch.cloud.google.com/oauth-redirect`
   * `https://discoveryengine.googleapis.com/oauth2/callback`
6. Click **Create**.
7. Copy the generated **Client ID** and **Client Secret**.

---

### Step 4: Register as an A2A Agent in Gemini Enterprise

1. Navigate to **Gemini Enterprise** > **Agents** (or **Agent Designer** > **Extensions & Connectors**).
2. Click **+ Add Agent** (or **Register Agent**).
3. Select **A2A (Agent-to-Agent)**.
4. **Paste the downloaded JSON Agent Card** from Step 2 into the configuration box.
5. In the **Authentication** section, configure these exact parameters:

| Parameter | Exact Value |
| :--- | :--- |
| **Authentication Type** | **OAuth 2.0** |
| **Authorization URL** | `https://accounts.google.com/o/oauth2/v2/auth?access_type=offline&prompt=consent` |
| **Token URL** | `https://oauth2.googleapis.com/token` |
| **Client ID** | *(Paste Client ID from Step 3)* |
| **Client Secret** | *(Paste Client Secret from Step 3)* |
| **Scopes** | `https://www.googleapis.com/auth/cloud-platform https://www.googleapis.com/auth/bigquery.readonly openid https://www.googleapis.com/auth/userinfo.email` *(Space-separated, no commas)* |
| **PKCE Verification** | **Unchecked** |

6. Click **Save & Activate**.

---

### Step 5: Grant User Access & Workforce Identity (WIF) Permissions

Once the A2A agent is registered in Gemini Enterprise, you must grant users access so it appears in their chat:

1. In **Gemini Enterprise**, navigate to the **Agents** management page.
2. Click on your newly registered A2A agent (**`GE Analytics`**).
3. Open the **Permissions / Access Control** tab.
4. Add the specific corporate users, groups, or your **Workforce Identity Federation (WIF) Pool** who should have access to interact with the agent.
5. Save the permissions.

---

## 💬 Step 5: Start Using the Agent

1. Refresh your browser on the **Gemini Enterprise App**.
2. Open the chat with **`GE Analytics`** (or `@mention` the agent).
3. On the first interaction, click the one-time **Authorize / Sign in with Google** prompt.
4. Ask any question in natural language:

### 👔 Sample Executive Prompts:
* *"What is our overall platform usage and Daily Active User (DAU) breakdown for this month?"*
* *"Show me the adoption breakdown between users who only use Chat versus users who use NotebookLM and Custom Agents."*
* *"Which custom agents are most popular ranked by total interaction volume?"*
* *"Who created our custom agents and what are their system instructions?"*
* *"How many active users do we have per engine?"*
* *"Show me power users who interact with all 3 features."*

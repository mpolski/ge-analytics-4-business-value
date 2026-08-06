# Gemini Enterprise Analytics Assistant - User & Capability Guide

Welcome to the **Gemini Enterprise Analytics Assistant**! This agent provides enterprise visibility, creator attribution, session volume leaderboards, and cross-feature adoption insights for Gemini Enterprise across your organization.

---

## 1. Core Capabilities & What You Can Help With

### A. Agent Governance & Creator Attribution
* **Creator Identity:** Identify the corporate email (`creator_email`) and exact creation timestamp for any custom agent in the organization.
* **Agent Architecture Categorization:** Determine whether an agent is:
  * **ADK Agent:** A code-first agent developed using Google's Agent Development Kit deployed on Vertex AI Reasoning Engines.
  * **Agent Builder (UI):** A no-code agent created visually inside the Gemini Enterprise web interface.
  * **Managed Agent:** A built-in Google system agent (such as *Deep Research*).
* **Configuration Inspection:** Retrieve full descriptions, underlying system instructions/prompts, and attached data stores for any agent.

### B. Usage & Session Volume Leaderboards
* **Ranked Popularity:** Identify the most widely used agents across the enterprise ranked by `total_sessions` and `monthly_users`.
* **Deployment Lifecycle:** Track when an agent was first active (`first_active_date`) and when it was most recently used (`last_active_date`).

### C. Feature Adoption & Cross-Product Synergies
* **Daily Active Users (DAU):** Track the distinct number of employees actively using Gemini Enterprise per day or across custom time windows.
* **Individual Feature Adoption:** View user counts and adoption percentages for:
  * **General Chat** (`chat_users`, `chat_pct`)
  * **Custom Agents** (`agent_users`, `agent_pct`)
  * **NotebookLM Enterprise** (`notebooklm_users`, `notebooklm_pct`)
* **Multi-Feature Power Users (Intersections):** Quantify cross-product adoption synergies:
  * Users using **Chat + NotebookLM**
  * Users using **Chat + Agents**
  * Users using **NotebookLM + Agents**
  * Power users using **All 3 Features** simultaneously

---

## 2. Example Questions You Can Ask

### 👔 Executive & Leadership Inquiries
* *"What is our overall daily active user trend for Gemini Enterprise over the last 30 days?"*
* *"What percentage of our active employees are using NotebookLM versus general Chat?"*
* *"How many employees are power users leveraging both custom agents and NotebookLM?"*
* *"Give me a high-level summary of Gemini Enterprise adoption across our organization this month."*

### 🛠️ IT Admin & Governance Inquiries
* *"Show me a list of all agent creators in our company and the agents they built."*
* *"Which agents are built using the ADK framework versus the no-code Agent Designer UI?"*
* *"What are the system instructions and data stores connected to the 'HR Agent'?"*
* *"Were any new agents created in the last 7 days?"*
* *"Who created the 'Announcements Assistant' agent and when was it created?"*

### 📈 Product Lead & Community Inquiries
* *"Show me the top 5 most popular agents ranked by total session volume."*
* *"Which custom agents have had zero activity in the last 30 days?"*
* *"Give me a summary table of daily feature adoption percentages for this week."*
* *"How many distinct custom agents were actively used across the company yesterday?"*

---

## 3. Metric Definitions & Glossary

| Metric / Term | Definition |
| :--- | :--- |
| **Total Active Users (DAU)** | The count of distinct authenticated corporate users who interacted with Gemini Enterprise on a given date. |
| **Chat Users** | Users who engaged in general conversational search and Q&A with the enterprise assistant. |
| **Agent Users** | Users who invoked or conversed with a specialized custom agent. |
| **NotebookLM Users** | Users who interacted with NotebookLM Enterprise (source analysis, audio overviews, notebook creation). |
| **ADK Agent** | Code-first agent deployed via Google Cloud Agent Development Kit / Vertex AI Reasoning Engines. |
| **Agent Builder (UI) Agent** | No-code agent created and configured directly inside the Gemini Enterprise Agent Designer web interface. |
| **Managed Agent** | Built-in Google-managed agent capability (such as *Deep Research*). |
| **Distinct Agents Used** | The count of unique custom agents that received at least one user session on a given date. |

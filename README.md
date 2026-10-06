# Meridian Commerce — AI-Powered Customer Support Automation System

Meridian Commerce is a portfolio project that demonstrates how a customer-support operation can combine **PostgreSQL, Python, deterministic business rules, LLM-based classification, human-in-the-loop controls, response safety checks, and read-only analytics** into a controlled support automation pipeline.

The project is intentionally designed around a key principle:

> AI can assist the support process, but deterministic business rules and human review remain authoritative where risk is higher.

The system does not send emails, issue refunds, modify customer accounts, or make autonomous business decisions.

---

## Project Overview

Meridian Commerce simulates a commerce company that receives customer-support tickets related to orders, products, payments, accounts, refunds, complaints, and general support.

The pipeline processes a support ticket through several controlled stages:

```text
Customer Support Ticket
        │
        ▼
PostgreSQL
        │
        ▼
AI Classification
        │
        ▼
Deterministic Business Rules
        │
        ▼
Human-in-the-Loop Decision
        │
        ▼
AI Response Layer
        │
        ▼
Safety Scanner
        │
        ▼
Stored Draft / Blocked Response
        │
        ▼
Read-Only Analytics
        │
        ▼
Power BI-Ready Data Layer
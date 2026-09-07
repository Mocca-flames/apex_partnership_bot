# APEX Logistics Partner Network — Implementation & Execution Plan

**Project:** SADC Cross-Border Lead Generation & Student Partner Program

**Core Stack:** FastAPI (Python) + PostgreSQL (Neon) + Docker + Baileys WhatsApp Gateway (Node.js)

**Deployment Target:** Single VM with Docker Compose

**Target Scope:** 20–50 Student Partners | Manual Vetting & Payouts | Zero Dashboard Overhead

---

## Executive System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Docker Compose Stack                            │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────────────┐  │
│  │   FastAPI    │◄──►│  PostgreSQL  │    │   Baileys Service (Node.js)  │  │
│  │   (Python)   │    │   (Neon)     │    │   WhatsApp Gateway           │  │
│  └──────────────┘    └──────────────┘    └──────────────────────────────┘  │
│         │                                        │                          │
│         │              WhatsApp                   │                          │
│         │            ┌──────────┐                 │                          │
│         └───────────►│  Student │◄────────────────┘                          │
│                      │   Phones │                                           │
│                      └──────────┘                                           │
│                             │                                                │
│                             ▼                                                │
│                      ┌──────────────┐                                        │
│                      │  APEX Staff │                                        │
│                      │    Bot      │                                        │
│                      └──────────────┘                                        │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Data Flow:**
```
[Student Web Signup] ──► [FastAPI / PostgreSQL] ──► [Generates OTP]
                                                           │
                                                           ▼
 [Student WhatsApp]   ──► [Baileys Gateway]        ──► [Webhook → FastAPI]
                                                           │
                                                           ▼
 [APEX Staff Bot]     ◄── [Role-Based Handler]     ◄── [State Machine]
```

---

## Key Principles

- **Zero Dashboard UI:** All student and APEX staff interactions take place via WhatsApp interactive flows and slash commands.
- **Baileys-First Gateway:** WhatsApp connectivity via Baileys (Node.js) running as a dedicated Docker service. Adapter interface allows future integration of Meta WhatsApp Cloud API.
- **Docker-Native Architecture:** Entire stack containerized via Docker Compose for consistent development, staging, and production environments.
- **Strict Gatekeeping:** Transporter phone numbers act as unique keys to prevent lead duplication across student submissions.
- **Phase-Gated Execution:** No phase begins until the previous phase's Testing & Verification Gate passes 100%.

---

## Session Persistence Strategy (VM Deployment)

Baileys WhatsApp sessions are persisted via a **local volume mount** on the VM:

```yaml
# docker-compose.yml
services:
  baileys-gateway:
    volumes:
      - ./baileys-sessions:/app/sessions  # Host directory → Container directory
```

**How it works:**
- `./baileys-sessions/` is created on the VM filesystem.
- WhatsApp authentication QR code / session tokens are stored here.
- Container restart or rebuild → session preserved (no re-SCAN required).
- First deployment requires scanning QR code once; subsequent runs use stored session.

**Directory structure after first scan:**
```
baileys-sessions/
├── session-xxx.json      # Baileys auth state
├── keys/                  # Encryption keys
└── ...
```

**Important:** Back up `baileys-sessions/` directory for disaster recovery.

---

## Project Structure

```
apex-partnership/
├── docker-compose.yml          # Main orchestration
├── docker-compose.dev.yml      # Development overrides
├── docker-compose.prod.yml     # Production overrides
├── backend/                    # FastAPI Python application
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── routers/
│   │   └── adapters/
│   └── alembic/                # Database migrations
├── baileys-gateway/            # Node.js WhatsApp gateway service
│   ├── Dockerfile
│   ├── package.json
│   ├── src/
│   │   ├── index.js            # Baileys connection manager
│   │   ├── handlers/           # Message handlers
│   │   └── lib/                # Baileys session store
│   └── sessions/               # Baileys auth sessions (volume-mounted from host)
├── nginx/                      # Reverse proxy (optional)
│   └── default.conf
├── .env.example
└── PLAN.md
```

---

## Phase 1: Core Database Architecture & Messaging Adapter Layer

### Objective
Establish the database schema, Docker infrastructure, environment configurations, and build a decoupled Messaging Adapter interface for the Baileys gateway.

### Tasks

- [ ] **Docker Compose Setup:**
  - Define `docker-compose.yml` with FastAPI, Baileys Gateway, and PostgreSQL services.
  - Configure shared network between services.
  - Set up volume mounts for Baileys session persistence.
- [ ] **Database Provisioning:** Set up PostgreSQL instance on Neon (cloud) or local container.
- [ ] **Database Schema Build:** Execute migrations for core tables:
  - `students`: Demographic data (lead_id, first_name, surname, email, phone, university, field, study_year, whatsapp_number, auth_passcode, status).
  - `transporters` (Leads): Transporter details (id, student_id, company_name, fleet_owner_phone, truck_count, truck_type, status, created_at).
  - `apex_staff`: Whitelisted staff phone numbers (phone_number, staff_name, role).
  - `audit_logs`: Logging administrative commands and fraud events.
- [ ] **FastAPI Base Setup:** Initialize repository structure (config, database, models, schemas, routers).
- [ ] **Baileys Gateway Service:**
  - Build `BaileysAdapter` to normalize Node.js WebSocket payloads into `InboundMessage` domain model (sender_phone, text_content, media_url, raw_payload).
  - Implement Baileys session persistence via local volume mount (survives container restarts).
  - Create outbound message queue (Redis or in-memory) for FastAPI → Baileys communication.
  - Design future `MetaCloudApiAdapter` interface for WhatsApp Cloud API migration.

### Phase 1 Deliverables
- Docker Compose stack with FastAPI and Baileys Gateway services.
- Fully initialized PostgreSQL database schema.
- Working `/webhook/whatsapp` endpoint receiving normalized payloads from Baileys gateway.
- Baileys session persistence via local volume mount (`./baileys-sessions:/app/sessions`).

### Testing & Verification Gate 1

1. **Schema Integrity:** Verify foreign key constraints, indexes on `transporters.fleet_owner_phone` and `students.whatsapp_number`.
2. **Docker Health Checks:** Confirm all containers are healthy via `docker compose ps`.
3. **Baileys Connection Test:** Verify Baileys gateway connects to WhatsApp and relays inbound messages to FastAPI webhook.
4. **Outbound Route Verification:** Confirm outbound messages from FastAPI are dispatched through Baileys gateway to WhatsApp.

---

## Phase 2: Web Handshake, OTP Generation & Phone Linking Engine

### Objective
Connect the existing Web Signup UI to the backend, generate OTPs, and link student web records to their verified WhatsApp phone numbers.

### Tasks

- [ ] **Web Signup API Endpoint (POST /api/v1/students/signup):**
  - Ingest signup payload matching Apex Leads.xlsx structure.
  - Insert record into `students` table with initial status `UNVERIFIED`.
  - Generate a unique 6-digit passcode (e.g., `AUTH-849201`).
  - Return bot phone number, dynamic click-to-chat link (`wa.me/...`), and passcode to the Web UI.
- [ ] **WhatsApp OTP Linker Logic:**
  - Webhook listener traps inbound messages starting with `AUTH-`.
  - Look up matching passcode in `students` table.
  - Security Check: Validate if `whatsapp_number` is already bound to another student.
  - Update student record: set `whatsapp_number` = incoming_sender_phone, set `status` = `TUTORIAL`, clear `auth_passcode`.
  - Send welcome response via WhatsApp initiating the onboarding tutorial.

### Phase 2 Deliverables
- Functional signup bridge linking Web UI registrations to WhatsApp accounts.
- Automated verification system enforcing 1:1 pairing between web registration and WhatsApp number.

### Testing & Verification Gate 2

1. **Valid Signup Flow:** Complete web signup, obtain OTP `AUTH-123456`, send via WhatsApp. Verify DB status transitions from `UNVERIFIED` to `TUTORIAL` and `whatsapp_number` populates accurately.
2. **Replay & Duplication Attack:** Attempt to reuse an already consumed OTP. Verify the system rejects it.
3. **Number Hijack Test:** Attempt to link a second student account using an already bound WhatsApp phone number. Verify system returns an authorization error.

---

## Phase 3: Interactive Onboarding, Tutorial & Testing Engine

### Objective
Educate students on cross-border load requirements and enforce a 3-strike dummy submission test before granting active lead submission privileges.

### Tasks

- [x] **State Machine Router Middleware:** Route inbound messages based on student DB status (`UNVERIFIED`, `TUTORIAL`, `ACTIVE`, `ADMIN_HOLD`, `PERMANENT_BAN`).
- [x] **Tutorial Payload Dispatcher:**
  - Dispatch introductory PDF/Image guide explaining load criteria (Superlink / Lowbed specs, SADC cross-border routes).
  - Issue practice prompt with dummy company details.
- [x] **3-Strike Evaluation Engine:**
  - Track test attempt counter in student session/DB (`tutorial_attempts`).
  - Validate dummy submission against expected format (Dummy Phone, Dummy Company, Dummy Truck Count).
  - **Pass:** Update student status to `ACTIVE`. Dispatch success message + interactive menu.
  - **Fail (Attempts < 3):** Increment counter, reply with explicit feedback on what was wrong, prompt retry.
  - **Fail (Attempt == 3):** Update status to `ADMIN_HOLD`. Send notification to APEX Staff WhatsApp group with chat link for manual intervention.

### Phase 3 Deliverables
- Automated tutorial state machine with media delivery capabilities.
- Robust evaluation engine with error counter, state progression, and staff escalation triggers.

### Testing & Verification Gate 3

1. **Happy Path:** Submit correct dummy data on first attempt. Verify immediate upgrade to `ACTIVE` status.
2. **Error Recovery:** Intentionally fail 2 attempts, then pass on 3rd attempt. Verify upgrade to `ACTIVE`.
3. **Escalation Trigger:** Intentionally fail 3 times. Verify DB updates to `ADMIN_HOLD` and APEX Staff alert dispatches to WhatsApp. Confirm bot blocks further student commands while in `ADMIN_HOLD`.

---

## Phase 4: Lead Intake & Anti-Duplication Engine

### Objective
Enable `ACTIVE` students to submit fleet leads while strictly enforcing anti-duplication rules based on the fleet manager's phone number, without causing message clutter.

### Tasks

- [ ] **Interactive Lead Submission Flow:**
  - **Step 1:** Prompt for Fleet Owner / Manager Cellphone Number.
    - Immediate Check: Query `transporters` table for `fleet_owner_phone`.
    - If found: Cancel submission instantly. Send non-cluttered response: "❌ Transporter phone number already registered in APEX network."
  - **Step 2:** Prompt for Company Name.
  - **Step 3:** Prompt for Truck Count.
  - **Step 4:** Prompt for Truck Type using WhatsApp Interactive Buttons (Superlink, Lowbed, Mixed).
- [ ] **Lead Persistence:**
  - Save lead to `transporters` with status `NEW_LEAD`.
  - Link lead to `student_id`.
  - Dispatch automated alert to APEX Staff WhatsApp line (`/pending` queue).
- [ ] **Student Pipeline Summary (`/status` or Button Click):**
  - Query active leads belonging to `student_id`.
  - Format response into simplified student-facing milestones:
    - `NEW_LEAD` → Under Review
    - `VETTED` → Verified (Awaiting Load)
    - `LOADED` → Truck Loaded (Commission Pending)
    - `PAID` → Commission Paid!
    - `REJECTED_*` → Closed / Rejected

### Phase 4 Deliverables
- Structured, conversational lead intake flow with button controls.
- Primary-key phone deduplication engine.
- Student pipeline status view.

### Testing & Verification Gate 4

1. **Lead Submission:** Submit a unique lead (e.g., `0820000000`). Confirm database entry creation with status `NEW_LEAD`.
2. **Duplication Rejection:** Have Student B attempt to submit `0820000000`. Confirm immediate rejection and verify Student B cannot see Student A's identity.
3. **Data Integrity Test:** Submit invalid inputs (e.g., text instead of number for truck count). Verify input validation catches error and reprompts gently.

---

## Phase 5: APEX Staff Operations & Fraud Control Engine

### Objective
Equip APEX staff with WhatsApp-based command controls to vet companies, log loaded trucks, trigger notifications, execute fraud bans, and handle manual payouts.

### Tasks

- [ ] **Role-Based Whitelist Middleware:**
  - Intercept incoming messages. If command starts with `/` (admin command), verify `sender_phone` exists in `apex_staff` table. Block unauthorized calls silently or return permission error.
- [ ] **Staff Slash Command Implementations:**

  - `/pending`: Fetch and list up to 5 unvetted leads (`NEW_LEAD`).
  - `/vet [lead_id]`: Update lead status to `VETTED`.
  - `/load [lead_id] [truck_count]`: Update status to `LOADED`. Calculate commission (`truck_count * R1,000`). Trigger automated WhatsApp notification to student: "🚚 Great news! [Company Name] truck loaded. Commission flagged."
  - `/payouts`: Display all leads in `LOADED` status with associated student banking details.
  - `/pay [student_id] [lead_id]`: Update lead status to `PAID`. Send confirmation message to student: "💰 R[Amount] payout processed to your bank account!"
  - `/fraud [student_id]`:
    - Set student status to `PERMANENT_BAN`.
    - Set all associated pending leads to `REJECTED_FRAUD`.
    - Revoke active WhatsApp session.
    - Send termination notification to student.
- [ ] **Rate-Limiting & Security Hardening:**
  - Implement basic message rate-limiter (e.g., max 10 messages/minute per user) to mitigate spam loops.

### Phase 5 Deliverables
- Full suite of administrative staff slash commands operating natively inside WhatsApp.
- Fraud isolation and instant account termination pipeline.
- Automated student notification system tied to staff state updates.

### Testing & Verification Gate 5

1. **Lifecycle End-to-End Test:**
   - Student submits Lead X (2 trucks).
   - Staff executes `/pending` → sees Lead X.
   - Staff executes `/vet [lead_id]` → status becomes `VETTED`.
   - Staff executes `/load [lead_id] 2` → status becomes `LOADED`, student receives load notification.
   - Staff executes `/payouts` → sees payout entry.
   - Staff executes `/pay [student_id] [lead_id]` → status becomes `PAID`, student receives payout notification.
2. **Fraud Execution Test:**
   - Execute `/fraud [student_id]` on a test user.
   - Verify status becomes `PERMANENT_BAN`, all pending leads are marked `REJECTED_FRAUD`, and subsequent incoming messages from the student are ignored.
3. **Security Test:**
   - Attempt to execute `/pending` or `/fraud` from a non-whitelisted student phone number. Confirm strict rejection.

---

## Phase 6: Pilot Staging, Field Trial & Operational Handoff

### Objective
Deploy the system to production infrastructure, configure the WhatsApp connection via Baileys, and run the live field trial with the student cohort.

### Tasks

- [ ] **Infrastructure Deployment:**
  - Deploy to production VM with Docker Compose.
  - Configure PostgreSQL database connections and SSL.
  - Mount local volume for Baileys session persistence (survives container restarts).
- [ ] **Gateway Setup:**
  - Link dedicated APEX operational SIM card to Baileys gateway.
  - Verify session persistence across container restarts using local volume mount.
- [ ] **Onboard Pilot Cohort:**
  - Distribute Web Signup link to 20 selected student partners.
  - Monitor OTP linkings, tutorial completions, and initial lead submissions.
- [ ] **Real-Time Operational Monitoring:**
  - Track Docker container logs, API response latency, and database connection pools.
  - Handle manual staff telephone calls to fleet owners as leads arrive in the `/pending` queue.

### Phase 6 Deliverables
- Live, production-grade Docker stack hosting 20 active student partners.
- Fully operational APEX staff workflow managing cross-border SADC truck leads.

### Testing & Verification Gate 6 (Final Sign-off)

1. **Load/Stress Verification:** Run simulated webhook tests mimicking 20 active concurrent students submitting messages simultaneously. Verify database stability and zero dropped requests.
2. **Pilot Audit:** Review database state after 7 days of live operations:
   - Ensure zero duplicate phone numbers exist in `transporters`.
   - Confirm all paid commissions match manual EFT logs.
   - Verify zero unauthorized staff command executions.

---

## Future: Meta WhatsApp Cloud API Migration

When ready to migrate from Baileys to Meta WhatsApp Cloud API:

1. Implement `MetaCloudApiAdapter` adhering to the existing `MessageSenderInterface`.
2. Set `MESSAGING_PROVIDER=official` in environment.
3. Configure webhook URL in Meta Developer Console.
4. Decommission Baileys gateway service from Docker Compose.

The adapter interface ensures zero changes to FastAPI routing logic during migration.

# APEX Partnership — Student Bot Commands

You're registered. You're in the system. This is everything you need to know to start earning.

---

## Step 1: Get the Tutorial PDF

Send:

```
TUTORIAL
```

The bot sends you a PDF. **Read it** — there's a practice test next.

---

## Step 2: Pass the Practice Test

When you're ready, send:

```
READY
```

The bot asks you to submit a practice lead. You must reply with **all three fields in one message**, exactly like this:

```
PHONE: 27820000000
COMPANY: APEX PRACTICE LOGISTICS
TRUCKS: 5
```

### Practice Test Rules

| Field    | Must Be                        |
|----------|--------------------------------|
| PHONE    | `27820000000`                  |
| COMPANY  | `APEX PRACTICE LOGISTICS`      |
| TRUCKS   | `5`                            |

> **You get 3 attempts.** Fail all 3 and your account goes on ADMIN_HOLD — APEX staff will need to reactivate you.

If you pass, the bot confirms:

> Tutorial passed! Your account is now ACTIVE. You may submit transporter leads.

---

## Step 3: Submit a Lead

Once you're ACTIVE, send any of these to start:

```
LEAD
```

```
SUBMIT LEAD
```

```
/LEAD
```

```
NEW LEAD
```

The bot walks you through **4 steps**. Reply to each one separately.

### Step 1 — Fleet Owner Phone

> Send the fleet owner / manager cellphone number.

Send the number **with country code** (e.g., `27821234567`).

- 10–15 digits, numbers only
- **No duplicates** — if this number is already in the system, it's rejected immediately

### Step 2 — Company Name

> What is the transporter company name?

Send the full company name (max 255 characters).

### Step 3 — Truck Count

> How many trucks does the transporter operate? Send a whole number.

Send a whole number (1–10,000).

### Step 4 — Truck Type

> Select the truck type:

Choose one by tapping the button or typing the name/number:

| #   | Type       | Description                                    |
|-----|------------|------------------------------------------------|
| 1   | Superlink  | Interlink double trailer combination           |
| 2   | Lowbed     | Low-bed trailer for heavy/over-dimensional loads|
| 3   | Mixed      | Fleet with a combination of truck types         |

After the 4th step, the bot confirms:

> Lead received and queued for APEX review. Reply **STATUS** to track it.

---

## Step 4: Check Your Status

Send:

```
STATUS
```

or

```
/STATUS
```

You'll see all your leads and where they stand:

```
Your APEX lead pipeline:
• Trans Freight Logistics cc (12 trucks): Verified (Awaiting Load)
• Quick Haulage Pty Ltd (5 trucks): Under Review
• SADC Movers (8 trucks): Commission Paid!
```

### What the Statuses Mean

| Status | Meaning |
|--------|---------|
| Under Review | Lead submitted, waiting for APEX staff to vet it |
| Verified (Awaiting Load) | Transporter verified, waiting to load trucks |
| Truck Loaded (Commission Pending) | Trucks loaded, commission being processed |
| Commission Paid! | R1,000 per truck paid to your bank account |

---

## Command Cheat Sheet

| Command | What It Does |
|---------|-------------|
| `TUTORIAL` | Sends the PDF guide |
| `READY` | Starts the practice test |
| `LEAD` / `SUBMIT LEAD` / `/LEAD` / `NEW LEAD` | Starts lead submission wizard |
| `STATUS` / `/STATUS` | Shows your lead pipeline |

---

## Lead Lifecycle

```
YOU SUBMIT → Under Review → Verified → Loaded → Paid
```

- **Under Review** — APEX staff are checking the transporter
- **Verified** — Transporter is legitimate, waiting to load
- **Loaded** — Trucks loaded, your commission is flagged (you get a WhatsApp alert)
- **Paid** — R1,000 per truck sent to your bank (you get a WhatsApp alert)

---

## How Much You Earn

| Trucks Loaded | Your Commission |
|---------------|----------------|
| 1             | R1,000         |
| 5             | R5,000         |
| 10            | R10,000        |
| 25            | R25,000        |

---

## Rules

- **One phone number per account** — your WhatsApp is permanently linked
- **No duplicate leads** — the fleet owner's phone number must be unique in the system
- **No spam** — max 10 messages per minute
- **No fake leads** — fraudulent submissions result in a permanent ban
- **No editing** — leads can't be changed after submission

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Phone number rejected | That transporter is already in the APEX network — try a different one |
| Account on ADMIN_HOLD | You failed 3 practice test attempts. Wait for APEX staff to contact you |
| No response after submitting | Use `STATUS` to check. Processing takes time |
| Didn't get paid alert | Use `STATUS` to see if lead is marked **Commission Paid!** |

---

## Need Help?

- Reply to any APEX bot message with your question
- APEX staff will respond during business hours
- For urgent issues, contact your campus APEX coordinator

---

*APEX Partnership — SADC Cross-Border Lead Generation Program*
*Student Partner Tutorial v1.0*

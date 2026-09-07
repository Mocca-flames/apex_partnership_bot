# APEX Partnership

## Current Phase: 4

The project now includes the Phase 4 lead intake engine: ACTIVE students can submit transporter leads through WhatsApp, duplicate fleet-owner numbers are rejected, leads are persisted as `NEW_LEAD`, staff receive queue alerts, and students can reply `STATUS` to view their pipeline.

### Start

1. Copy `.env.example` to `.env` and replace the development secrets.
2. Start the stack:

```sh
docker compose up --build
```

3. Scan the QR code printed by `baileys-gateway` on first start. Authentication data is persisted in `./baileys-sessions`.
4. Check service health:

```sh
curl http://localhost:8000/health
curl http://localhost:3000/health
docker compose ps
```

The backend migration runs automatically before FastAPI starts. The normalized inbound webhook is `POST /webhook/whatsapp`; outbound messages use `POST /api/v1/messages`.

Staff slash commands and vetting operations remain scheduled for Phase 5.

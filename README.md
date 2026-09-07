# APEX Partnership

## Phase 1

Phase 1 provides the Docker Compose stack, PostgreSQL schema migrations, FastAPI WhatsApp webhook, and Baileys gateway adapter.

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

Phase 2 signup, OTP linking, tutorial flows, lead intake, and staff commands are intentionally not included in this Phase 1 implementation.

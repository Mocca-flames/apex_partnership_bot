# APEX Partnership

## Current Phase: 5

The project now includes the Phase 5 staff operations engine: APEX staff can vet leads (`/vet`), mark trucks loaded (`/load`), process payouts (`/pay`), and ban fraudulent students (`/fraud`) directly from WhatsApp. Rate limiting (10 msgs/min) and role-based access control protect admin commands. `PERMANENT_BAN` status is enforced.

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

Staff slash commands are now active (Phase 5).

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

import express from "express";
import makeWASocket, {
  Browsers,
  DisconnectReason,
  useMultiFileAuthState,
} from "@whiskeysockets/baileys";
import { Boom } from "@hapi/boom";
import pino from "pino";
import qrcode from "qrcode-terminal";

const port = Number(process.env.GATEWAY_PORT || 3000);
const sessionsPath = "/app/sessions";
const webhookUrl = process.env.BACKEND_WEBHOOK_URL || "http://backend:8000/webhook/whatsapp";
const webhookSecret = process.env.WEBHOOK_SHARED_SECRET || "dev-webhook-secret";
const logger = pino({ level: process.env.LOG_LEVEL || "info" });

let socket;
let connectionState = "starting";
let reconnectAttempts = 0;
const MAX_RECONNECT_ATTEMPTS = 5;
let outboundQueue = Promise.resolve();

function clearAuthState() {
  try {
    const files = fs.readdirSync(sessionsPath);
    for (const file of files) {
      fs.unlinkSync(path.join(sessionsPath, file));
    }
    logger.info("Cleared old auth state files");
  } catch (error) {
    logger.warn({ error }, "Failed to clear auth state");
  }
}

function normalizePhone(jid) {
  return jid.split(":")[0].split("@")[0];
}

function queueOutbound(recipientPhone, textContent, mediaUrl, mediaFilename, buttons) {
  const messageId = crypto.randomUUID();
  outboundQueue = outboundQueue.then(async () => {
    if (!socket || connectionState !== "open") {
      throw new Error("WhatsApp connection is not ready");
    }
    const jid = `${recipientPhone.replace(/[^0-9]/g, "")}@s.whatsapp.net`;
    if (mediaUrl) {
      await socket.sendMessage(jid, {
        document: { url: mediaUrl },
        mimetype: "application/pdf",
        fileName: mediaFilename || "APEX-Tutorial.pdf",
        caption: textContent,
      });
      return;
    }
    if (buttons?.length) {
      await socket.sendMessage(jid, {
        text: textContent,
        footer: "APEX Partnership",
        buttons: buttons.map((displayText, index) => ({
          buttonId: String(index + 1),
          buttonText: { displayText },
          type: 1,
        })),
      });
      return;
    }
    await socket.sendMessage(jid, { text: textContent });
  });
  return outboundQueue.then(() => messageId);
}

async function relayInbound(message) {
  const remoteJid = message.key?.remoteJid || "";
  if (!remoteJid || remoteJid === "status@broadcast" || message.key?.fromMe) return;
  const jid = message.key?.remoteJidAlt || message.key?.participant || remoteJid;

  const textContent = message.message?.conversation
    || message.message?.extendedTextMessage?.text
    || message.message?.imageMessage?.caption
    || message.message?.videoMessage?.caption
    || message.message?.buttonsResponseMessage?.selectedButtonId
    || message.message?.templateButtonReplyMessage?.selectedId
    || message.message?.listResponseMessage?.singleSelectReply?.selectedRowId
    || "";

  const payload = {
    sender_phone: normalizePhone(jid),
    text_content: textContent,
    media_url: null,
    raw_payload: message,
  };

  const response = await fetch(webhookUrl, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-webhook-secret": webhookSecret,
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(`Backend webhook returned ${response.status}`);
  }
}

async function connect() {
  const { state, saveCreds } = await useMultiFileAuthState(sessionsPath);
  socket = makeWASocket({
    auth: state,
    browser: Browsers.ubuntu("APEX Partnership Gateway"),
    logger: pino({ level: "silent" }),
    markOnlineOnConnect: false,
    printQRInTerminal: true,
  });

  socket.ev.on("creds.update", saveCreds);
  socket.ev.on("connection.update", async ({ connection, lastDisconnect, qr }) => {
    if (qr) {
      connectionState = "awaiting_qr";
      qrcode.generate(qr, { small: true });
      logger.info("Scan the QR code above to link the APEX WhatsApp account");
    }
    if (connection === "open") {
      connectionState = "open";
      reconnectAttempts = 0;
      logger.info("Baileys connection opened");
    }
    if (connection === "close") {
      connectionState = "closed";
      const statusCode = new Boom(lastDisconnect?.error)?.output?.statusCode;
      const isLoggedOut = statusCode === DisconnectReason.loggedOut;
      logger.warn({ statusCode, isLoggedOut }, "Baileys connection closed");

      if (isLoggedOut) {
        logger.info("Session invalid, clearing auth state and preparing for re-link");
        clearAuthState();
        connectionState = "awaiting_qr";
      }

      if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
        reconnectAttempts++;
        const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 30000);
        logger.info({ delay, attempt: reconnectAttempts }, "Reconnecting in milliseconds");
        setTimeout(() => connect().catch((error) => {
          logger.error({ error }, "Reconnection failed");
        }), delay);
      } else {
        logger.error("Max reconnection attempts reached, please restart the service");
      }
    }
  });
  socket.ev.on("messages.upsert", async ({ messages, type }) => {
    if (type !== "notify") return;
    for (const message of messages) {
      try {
        await relayInbound(message);
      } catch (error) {
        logger.error({ error }, "Failed to relay inbound WhatsApp message");
      }
    }
  });
}

const app = express();
app.use(express.json());
app.get("/health", (_request, response) => {
  response.json({ status: "ok", whatsapp_connection: connectionState });
});
app.post("/messages", async (request, response) => {
  const {
    recipient_phone: recipientPhone,
    text_content: textContent,
    media_url: mediaUrl,
    media_filename: mediaFilename,
    buttons,
  } = request.body;
  if (!recipientPhone || !textContent) {
    return response.status(400).json({ detail: "recipient_phone and text_content are required" });
  }
  try {
    const messageId = await queueOutbound(recipientPhone, textContent, mediaUrl, mediaFilename, buttons);
    return response.status(202).json({ accepted: true, message_id: messageId });
  } catch (error) {
    logger.error({ error }, "Failed to send outbound WhatsApp message");
    return response.status(503).json({ detail: "WhatsApp connection is not ready" });
  }
});

app.listen(port, () => logger.info({ port }, "Baileys gateway HTTP server listening"));
connect().catch((error) => {
  logger.error({ error }, "Failed to start Baileys connection");
  process.exitCode = 1;
});

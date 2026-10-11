"use strict";

/**
 * jev-log API — Almacena en UNA colección (jev_calls) cada llamada al modelo
 * Jev: la petición (state + questions + meta) y la respuesta (probabilidades,
 * tokens, latencia, costo) en un solo documento.
 *
 * POST /calls          → inserta { request, response, ... } y devuelve el _id
 * GET  /calls          → lista paginada (limit, skip, q)
 * GET  /calls/:id      → recupera una llamada completa
 * GET  /health         → readiness (Mongo ping)
 */

const express = require("express");
const { MongoClient } = require("mongodb");

const PORT = parseInt(process.env.PORT || "3000", 10);
const MONGO_URL = process.env.MONGO_URL ||
  "mongodb://jev:jevpass@mongodb:27017/jevlog?authSource=admin";
const DB_NAME = process.env.MONGO_DB || "jevlog";
const COLLECTION = "jev_calls"; // ← única colección del sistema

const client = new MongoClient(MONGO_URL, {
  serverSelectionTimeoutMS: 5000,
  connectTimeoutMS: 5000,
});
const app = express();
app.use(express.json({ limit: "2mb" }));

let collection = null;

async function connect() {
  await client.connect();
  const db = client.db(DB_NAME);
  collection = db.collection(COLLECTION);
  // Índices: consultas por typo de piloto, modelo y ventana temporal
  await collection.createIndex({ tick: 1 });
  await collection.createIndex({ created_at: -1 });
  await collection.createIndex({ "request.model": 1 });
  await collection.createIndex({ "request.pilot": 1 });
  console.log(`mongo connected: db=${DB_NAME} collection=${COLLECTION}`);
}

// ── POST /calls ──────────────────────────────────────────────────────────
app.post("/calls", async (req, res) => {
  try {
    const body = req.body || {};
    // La petición y la respuesta llegan juntas y quedan juntas para siempre:
    // un documento = una decisión de Jev completa (request + response).
    const doc = {
      created_at: new Date(),
      tick: Number.isInteger(body.tick) ? body.tick : null,
      request: {
        model: body.request?.model ?? "jev-latest",
        pilot: body.request?.pilot ?? null,
        prompt_version: body.request?.prompt_version ?? null,
        state: body.request?.state ?? null,        // estado estructurado v2
        questions: body.request?.questions ?? null, // movement/aim/interaction
      },
      response: {
        probabilities: body.response?.probabilities ?? null,
        confidence: body.response?.confidence ?? null,
        proposed_controls: body.response?.proposed_controls ?? null,
        guard_interventions: body.response?.guard_interventions ?? null,
        input_tokens: body.response?.input_tokens ?? null,
        cost_usd: body.response?.cost_usd ?? null,
        latency_ms: body.response?.latency_ms ?? null,
        model_id: body.response?.model_id ?? null,   // resuelto: jev-1.13.0
        raw: body.response?.raw ?? null,             // respuesta cruda si exist
      },
      metadata: body.metadata ?? {},
    };

    const result = await collection.insertOne(doc);
    res.status(201).json({
      inserted_id: result.insertedId,
      collection: COLLECTION,
      stored: { request: doc.request, response: doc.response },
    });
  } catch (err) {
    console.error("POST /calls failed:", err.message);
    res.status(500).json({ error: "insert_failed", detail: err.message });
  }
});

// ── GET /calls ──────────────────────────────────────────────────────────
app.get("/calls", async (req, res) => {
  try {
    const limit = Math.min(parseInt(req.query.limit || "20", 10) || 20, 100);
    const skip = Math.max(parseInt(req.query.skip || "0", 10) || 0, 0);
    const filter = {};
    if (req.query.pilot) filter["request.pilot"] = req.query.pilot;
    if (req.query.model) filter["request.model"] = req.query.model;
    if (req.query.tick) filter.tick = parseInt(req.query.tick, 10);
    const docs = await collection
      .find(filter, { projection: { "request.state": 0, "request.questions": 0 } })
      .sort({ created_at: -1 })
      .skip(skip)
      .limit(limit)
      .toArray();
    const total = await collection.countDocuments(filter);
    res.json({ total, count: docs.length, skip, limit, calls: docs });
  } catch (err) {
    console.error("GET /calls failed:", err.message);
    res.status(500).json({ error: "query_failed", detail: err.message });
  }
});

// ── GET /calls/:id ──────────────────────────────────────────────────────
app.get("/calls/:id", async (req, res) => {
  try {
    const { ObjectId } = require("mongodb");
    if (!ObjectId.isValid(req.params.id)) {
      return res.status(400).json({ error: "invalid_id" });
    }
    const doc = await collection.findOne({ _id: new ObjectId(req.params.id) });
    if (!doc) return res.status(404).json({ error: "not_found" });
    res.json(doc); // documento completo: request + response juntos
  } catch (err) {
    console.error("GET /calls/:id failed:", err.message);
    res.status(500).json({ error: "query_failed", detail: err.message });
  }
});

// ── GET /health ──────────────────────────────────────────────────────────
app.get("/health", async (_req, res) => {
  try {
    await client.db("admin").command({ ping: 1 });
    res.json({ ok: true, db: DB_NAME, collection: COLLECTION });
  } catch (err) {
    res.status(503).json({ ok: false, detail: err.message });
  }
});

// ── arranque ─────────────────────────────────────────────────────────────
(async () => {
  for (let attempt = 1; attempt <= 30; attempt++) {
    try {
      await connect();
      break;
    } catch (err) {
      if (attempt === 30) {
        console.error("mongo unreachable after 30 attempts:", err.message);
        process.exit(1);
      }
      console.log(`mongo not ready (attempt ${attempt}/30), retrying…`);
      await new Promise((r) => setTimeout(r, 2000));
    }
  }
  app.listen(PORT, () => console.log(`jev-log API listening on :${PORT}`));
})();

process.on("SIGINT", () => client.close().then(() => process.exit(0)));
process.on("SIGTERM", () => client.close().then(() => process.exit(0)));

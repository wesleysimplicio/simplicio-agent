#!/usr/bin/env node
// Minimal static file server for the Snake benchmark fixture. No third
// party dependency — Playwright's `webServer` launches this to serve
// index.html over http:// (localStorage does not behave consistently
// under file:// origins across browsers/headless modes, so a real origin
// is required for the persistence acceptance criterion).
import http from "node:http";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const PORT = Number(process.env.PORT || 4173);

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
};

const server = http.createServer(async (req, res) => {
  try {
    const urlPath = new URL(req.url, "http://localhost").pathname;
    const relative = urlPath === "/" ? "index.html" : urlPath.replace(/^\/+/, "");
    const filePath = path.join(ROOT, relative);
    if (!filePath.startsWith(ROOT)) {
      res.writeHead(403).end("forbidden");
      return;
    }
    const body = await readFile(filePath);
    const ext = path.extname(filePath);
    res.writeHead(200, { "content-type": MIME[ext] || "application/octet-stream" });
    res.end(body);
  } catch (err) {
    res.writeHead(404).end("not found");
  }
});

server.listen(PORT, () => {
  console.log(`snake_fixture static server listening on http://localhost:${PORT}`);
});

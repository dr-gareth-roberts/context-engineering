import express from "express";
import { createServer } from "http";
import path from "path";
import { fileURLToPath } from "url";
import { createProxyMiddleware } from "http-proxy-middleware";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

async function startServer() {
  const app = express();
  const server = createServer(app);

  app.get("/healthz", (_req, res) => {
    res.status(200).json({ status: "ok" });
  });

  // Setup proxy to FastAPI backend for /api routes
  const backendPort = Number(process.env.BACKEND_PORT || 8000);
  const backendUrl =
    process.env.BACKEND_URL || `http://127.0.0.1:${backendPort}`;

  const corsOrigin =
    process.env.CORS_ORIGIN ||
    (process.env.NODE_ENV === "production" ? "" : "*");

  const rateLimitWindowMs = Number(process.env.RATE_LIMIT_WINDOW_MS || 60_000);
  const rateLimitMax = Number(process.env.RATE_LIMIT_MAX || 120);

  const rateLimitState = new Map<
    string,
    { count: number; resetAtMs: number }
  >();

  app.use("/api", (req, res, next) => {
    if (corsOrigin) {
      res.header("Access-Control-Allow-Origin", corsOrigin);
      res.header(
        "Access-Control-Allow-Methods",
        "GET,POST,PUT,PATCH,DELETE,OPTIONS"
      );
      res.header(
        "Access-Control-Allow-Headers",
        "Content-Type, Authorization, X-Requested-With"
      );
    }

    if (req.method === "OPTIONS") {
      return res.sendStatus(204);
    }

    const ip = req.ip || req.socket.remoteAddress || "unknown";
    const now = Date.now();
    const existing = rateLimitState.get(ip);
    if (!existing || existing.resetAtMs <= now) {
      rateLimitState.set(ip, { count: 1, resetAtMs: now + rateLimitWindowMs });
      return next();
    }

    existing.count += 1;
    if (existing.count > rateLimitMax) {
      res
        .status(429)
        .json({
          error: "rate_limited",
          retryAfterMs: existing.resetAtMs - now,
        });
      return;
    }

    next();
  });

  app.use(
    "/api",
    createProxyMiddleware({
      target: backendUrl,
      changeOrigin: true,
      pathRewrite: {
        "^/api": "/api", // Keep /api prefix
      },
    })
  );

  // Serve static files from dist/public in production
  const staticPath =
    process.env.NODE_ENV === "production"
      ? path.resolve(__dirname, "public")
      : path.resolve(__dirname, "..", "dist", "public");

  app.use(express.static(staticPath));

  // Handle client-side routing - serve index.html for all routes
  app.get("*", (_req, res) => {
    res.sendFile(path.join(staticPath, "index.html"));
  });

  const port = process.env.PORT || 3000;

  server.listen(port, () => {
    console.log(`Server running on http://localhost:${port}/`);
    console.log(`Proxying /api to ${backendUrl}/`);
  });
}

startServer().catch(console.error);

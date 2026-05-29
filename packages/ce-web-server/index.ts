import express from "express";
import { createServer } from "http";
import path from "path";
import { fileURLToPath } from "url";
import { createProxyMiddleware } from "http-proxy-middleware";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

/**
 * Rate limiter with periodic cleanup to prevent memory leaks.
 * Entries are purged every `cleanupIntervalMs` to remove expired windows.
 */
function createRateLimiter(windowMs: number, maxRequests: number) {
  const state = new Map<string, { count: number; resetAtMs: number }>();
  const cleanupIntervalMs = Math.max(windowMs, 60_000);

  const cleanupTimer = setInterval(() => {
    const now = Date.now();
    for (const [ip, entry] of state) {
      if (entry.resetAtMs <= now) {
        state.delete(ip);
      }
    }
  }, cleanupIntervalMs);

  // Allow the process to exit even if the timer is still running
  cleanupTimer.unref();

  function check(ip: string): { allowed: boolean; retryAfterMs?: number } {
    const now = Date.now();
    const existing = state.get(ip);

    if (!existing || existing.resetAtMs <= now) {
      state.set(ip, { count: 1, resetAtMs: now + windowMs });
      return { allowed: true };
    }

    existing.count += 1;
    if (existing.count > maxRequests) {
      return { allowed: false, retryAfterMs: existing.resetAtMs - now };
    }

    return { allowed: true };
  }

  function dispose() {
    clearInterval(cleanupTimer);
    state.clear();
  }

  return { check, dispose };
}

/**
 * Reads a positive integer from an environment variable, falling back to a
 * default when the variable is unset, empty, or not a valid positive number.
 * Surfaces misconfiguration via console.warn instead of silently producing NaN.
 */
function intEnv(name: string, fallback: number): number {
  const raw = process.env[name];
  const n = raw === undefined || raw === "" ? fallback : Number(raw);
  if (!Number.isFinite(n) || n <= 0) {
    if (raw !== undefined && raw !== "") {
      console.warn(
        `Invalid ${name}=${JSON.stringify(raw)}; using default ${fallback}`
      );
    }
    return fallback;
  }
  return n;
}

async function startServer() {
  const app = express();

  // Trust the first proxy hop (standard for reverse proxies / load balancers).
  // This makes req.ip return the real client IP from X-Forwarded-For.
  app.set("trust proxy", 1);

  // ── Security headers (applied to all responses) ──────────────────────
  app.use((_req, res, next) => {
    res.setHeader("X-Content-Type-Options", "nosniff");
    res.setHeader("X-Frame-Options", "DENY");
    res.setHeader("X-XSS-Protection", "0");
    res.setHeader("Referrer-Policy", "strict-origin-when-cross-origin");
    res.setHeader(
      "Permissions-Policy",
      "camera=(), microphone=(), geolocation=()"
    );
    if (process.env.NODE_ENV === "production") {
      res.setHeader(
        "Strict-Transport-Security",
        "max-age=63072000; includeSubDomains"
      );
    }
    next();
  });

  const server = createServer(app);

  app.get("/healthz", (_req, res) => {
    res.status(200).json({ status: "ok" });
  });

  // ── Proxy configuration ──────────────────────────────────────────────
  const backendPort = intEnv("BACKEND_PORT", 8000);
  const backendUrl =
    process.env.BACKEND_URL || `http://127.0.0.1:${backendPort}`;

  // CORS: In production, require explicit CORS_ORIGIN. In development,
  // default to the local dev server origin so credentials work correctly.
  const corsOrigin =
    process.env.CORS_ORIGIN ||
    (process.env.NODE_ENV === "production"
      ? undefined
      : "http://localhost:3000");

  const rateLimitWindowMs = intEnv("RATE_LIMIT_WINDOW_MS", 60_000);
  const rateLimitMax = intEnv("RATE_LIMIT_MAX", 120);
  const rateLimiter = createRateLimiter(rateLimitWindowMs, rateLimitMax);

  // ── API middleware: CORS + rate limiting ──────────────────────────────
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
      res.header("Access-Control-Allow-Credentials", "true");
    }

    if (req.method === "OPTIONS") {
      return res.sendStatus(204);
    }

    const ip = req.ip || req.socket.remoteAddress || "unknown";
    const result = rateLimiter.check(ip);
    if (!result.allowed) {
      res.status(429).json({
        error: "rate_limited",
        retryAfterMs: result.retryAfterMs,
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
    })
  );

  // ── Static files & SPA fallback ─────────────────────────────────────
  const staticPath =
    process.env.NODE_ENV === "production"
      ? path.resolve(__dirname, "public")
      : path.resolve(__dirname, "..", "dist", "public");

  app.use(express.static(staticPath));

  // Handle client-side routing - serve index.html for all routes
  app.get("/{*splat}", (_req, res) => {
    res.sendFile(path.join(staticPath, "index.html"));
  });

  const port = process.env.PORT || 3000;

  server.listen(port, () => {
    console.warn(`Server running on http://localhost:${port}/`);
    console.warn(`Proxying /api to ${backendUrl}/`);
  });

  // ── Graceful shutdown ────────────────────────────────────────────────
  function shutdown(signal: string) {
    console.warn(`Received ${signal}, shutting down gracefully...`);
    rateLimiter.dispose();
    server.close(() => {
      console.warn("Server closed");
      process.exit(0);
    });
    // Force exit after 10s if connections are not drained
    setTimeout(() => {
      console.error("Forcing shutdown after timeout");
      process.exit(1);
    }, 10_000).unref();
  }

  process.on("SIGTERM", () => shutdown("SIGTERM"));
  process.on("SIGINT", () => shutdown("SIGINT"));
}

startServer().catch(err => {
  console.error("Failed to start server:", err);
  process.exit(1);
});

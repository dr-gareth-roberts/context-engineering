# Roadmap 03: Universal Context Proxy

## Objective

Provide a "Context-as-a-Service" layer that works with any language (Go, Rust, Ruby) by acting as a drop-in replacement for OpenAI/Anthropic API endpoints.

## Architecture

- **Server:** A FastAPI (Python) or Express (Node) server.
- **Endpoint:** Proxies `POST /v1/chat/completions`.
- **Logic Flow:**
  1.  Receive request from Client.
  2.  Extract `messages` and a custom header `X-CE-Budget`.
  3.  Convert `messages` into `ContextItems`.
  4.  Run the `pack()` algorithm to optimize the prompt.
  5.  Forward the optimized request to the real LLM Provider.
  6.  Return the response to the Client.

## Key Features

- **Automatic Memory:** The proxy can automatically store incoming messages in a `SqliteStore` based on a `session_id` header.
- **Header-based Configuration:** Configure `ScoringWeights` and `Strategy` via HTTP headers.
- **Streaming Support:** Must handle Server-Sent Events (SSE) for real-time responses.

## Deployment Options

1.  **Local Dev:** Run as a sidecar container in Docker.
2.  **Edge:** Deploy as a Cloudflare Worker or Vercel Function.

## Success Criteria

- A user can switch from standard OpenAI to the Proxy by changing only the `base_url`:
  ```python
  # Before
  client = OpenAI(api_key="...")
  # After
  client = OpenAI(api_key="...", base_url="http://localhost:8080/v1")
  ```

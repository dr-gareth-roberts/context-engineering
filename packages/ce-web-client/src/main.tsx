import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";

function installAnalytics(): void {
  const endpoint = import.meta.env.VITE_ANALYTICS_ENDPOINT?.trim();
  const websiteId = import.meta.env.VITE_ANALYTICS_WEBSITE_ID?.trim();

  if (!endpoint || !websiteId) {
    return;
  }

  if (document.querySelector(`script[data-website-id="${websiteId}"]`)) {
    return;
  }

  const script = document.createElement("script");
  script.defer = true;
  script.src = `${endpoint.replace(/\/+$/, "")}/umami`;
  script.dataset.websiteId = websiteId;
  document.head.appendChild(script);
}

installAnalytics();

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("Root element #root not found");
}

createRoot(rootElement).render(<App />);

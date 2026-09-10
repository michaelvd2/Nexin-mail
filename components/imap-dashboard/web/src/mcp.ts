import { App as McpApp } from "@modelcontextprotocol/ext-apps";
import type { ToolResult } from "./types";

type HostNotification = (method: string, params: unknown) => void;

const listeners = new Set<HostNotification>();
let latestResult: ToolResult | undefined;

export const isStandalone = window.self === window.top || new URLSearchParams(window.location.search).has("standalone");

if (isStandalone) document.documentElement.dataset.imapDashboardPresentation = "standalone";

const app = isStandalone
  ? undefined
  : new McpApp(
      { name: "nexin-mail-ui", version: "0.1.2" },
      { availableDisplayModes: ["fullscreen"] },
      { autoResize: true },
    );

if (app) {
  app.addEventListener("toolresult", (result) => {
    latestResult = result as unknown as ToolResult;
    listeners.forEach((listener) => listener("ui/notifications/tool-result", result));
  });
  app.addEventListener("hostcontextchanged", (context) => {
    if (context.displayMode === "fullscreen") {
      document.documentElement.dataset.imapDashboardPresentation = "side-panel";
      return;
    }
    if (context.displayMode === "inline") delete document.documentElement.dataset.imapDashboardPresentation;
  });
}

const appReady = app?.connect();
let sidePanelRequest: Promise<boolean> | undefined;
let sidePanelRequested = false;

/** Codex exposes its side-panel expansion through the OpenAI fullscreen display mode. */
export function ensureSidePanel(): Promise<boolean> {
  if (isStandalone) return Promise.resolve(true);
  if (sidePanelRequest) return sidePanelRequest;
  if (sidePanelRequested) return Promise.resolve(app?.getHostContext()?.displayMode === "fullscreen");
  sidePanelRequested = true;
  sidePanelRequest = (async () => {
    if (!app || !appReady) return false;
    try {
      await appReady;
      const available = app.getHostContext()?.availableDisplayModes;
      if (available && !available.includes("fullscreen")) return false;
      const result = await app.requestDisplayMode({ mode: "fullscreen" });
      const opened = result.mode === "fullscreen";
      if (opened) document.documentElement.dataset.imapDashboardPresentation = "side-panel";
      return opened;
    } catch {
      return false;
    } finally {
      sidePanelRequest = undefined;
    }
  })();
  return sidePanelRequest;
}

export async function callTool<T>(name: string, args: Record<string, unknown>): Promise<ToolResult<T>> {
  if (isStandalone) throw new Error("Functieaanroepen zijn niet beschikbaar in de losse voorbeeldweergave.");
  if (!app || !appReady) throw new Error("De MCP Apps-host is niet beschikbaar.");
  await appReady;
  return app.callServerTool({ name, arguments: args }) as unknown as Promise<ToolResult<T>>;
}

export function subscribeHost(listener: HostNotification): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function initialToolResult(): ToolResult | undefined {
  if (latestResult) return latestResult;
  const compatibility = (window as Window & { openai?: { toolOutput?: unknown } }).openai?.toolOutput;
  return compatibility ? { structuredContent: compatibility } : undefined;
}

export function sendFollowUp(message: string): void {
  if (isStandalone || !app || !appReady) return;
  void appReady.then(() => app.sendMessage({ role: "user", content: [{ type: "text", text: message }] }));
}

export function extractStructured<T>(result: ToolResult<unknown>): T {
  if (result.structuredContent !== undefined) return result.structuredContent as T;
  const text = result.content?.find((item) => item.type === "text")?.text;
  if (!text) throw new Error("De mailfunctie gaf geen gestructureerd resultaat terug.");
  return JSON.parse(text) as T;
}

export function proposalId(result: ToolResult): string {
  let structured = result.structuredContent as { proposal_id?: unknown; proposal?: { proposal_id?: unknown } } | undefined;
  if (!structured) {
    const text = result.content?.find((item) => item.type === "text")?.text;
    if (text) {
      try { structured = JSON.parse(text) as typeof structured; } catch { /* handled by validation below */ }
    }
  }
  const candidate = structured?.proposal_id ?? structured?.proposal?.proposal_id;
  if (typeof candidate !== "string" || !/^[0-9a-f]{16}$/i.test(candidate)) {
    throw new Error("De bevestigingsweergave ontving geen geldig actievoorstel.");
  }
  return candidate;
}

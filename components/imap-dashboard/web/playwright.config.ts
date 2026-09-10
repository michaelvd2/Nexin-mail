import os from "node:os";
import path from "node:path";
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  reporter: "line",
  outputDir: path.join(os.tmpdir(), "imap-dashboard-playwright"),
  use: {
    baseURL: "http://127.0.0.1:4180",
    trace: "off",
    screenshot: "off",
  },
  webServer: {
    command: "python -m http.server 4180 --bind 127.0.0.1 --directory ../src/imap_dashboard/ui",
    url: "http://127.0.0.1:4180/mail-app.html?standalone=1",
    reuseExistingServer: true,
  },
});

import { expect, test, vi } from "vitest";
import { waitForSetup } from "./setup-session";

test("resumes the same pending session until ready without a new form", async () => {
  const wait = vi.fn()
    .mockResolvedValueOnce({ status: "waiting_for_input", session_id: "same" })
    .mockResolvedValueOnce({ status: "checking_connection", session_id: "same" })
    .mockResolvedValueOnce({ status: "ready", session_id: "same", ui_session_id: "ui" });
  const result = await waitForSetup({ status: "starting", session_id: "same" }, wait, () => true, () => {});
  expect(result.status).toBe("ready");
  expect(wait.mock.calls).toEqual([["same"], ["same"], ["same"]]);
});
test.each(["cancelled", "failed", "interrupted"])("stops on %s without retry", async (status) => {
  const wait = vi.fn().mockResolvedValue({ status, session_id: "same" });
  const result = await waitForSetup({ status: "waiting_for_input", session_id: "same" }, wait, () => true, () => {});
  expect(result.status).toBe(status);
  expect(wait).toHaveBeenCalledTimes(1);
});
test("closing the dashboard ends its wait without cancelling the native session", async () => {
  const wait = vi.fn();
  await waitForSetup({ status: "waiting_for_input", session_id: "same" }, wait, () => false, () => {});
  expect(wait).not.toHaveBeenCalled();
});

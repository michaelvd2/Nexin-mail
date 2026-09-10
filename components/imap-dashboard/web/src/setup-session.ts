export type SetupResult = {
  result?: string; status?: string; session_id?: string;
  recovery?: { message?: string }; configured?: boolean;
  ui_session_id?: string; profile?: string; from_address?: string;
};
export async function waitForSetup(
  initial: SetupResult,
  wait: (sessionId: string) => Promise<SetupResult>,
  active: () => boolean,
  progress: (status: string) => void,
): Promise<SetupResult> {
  let result = initial;
  while (["starting", "waiting_for_input", "checking_connection"].includes(result.status ?? "") && result.session_id && active()) {
    progress(result.status!);
    result = await wait(result.session_id);
  }
  return result;
}

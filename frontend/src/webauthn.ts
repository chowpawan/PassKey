import { startAuthentication, startRegistration } from "@simplewebauthn/browser";
import { api } from "./api";

export async function registerPasskey(username: string): Promise<void> {
  const { options } = await api.registerBegin(username);
  const attestation = await startRegistration(options);
  await api.registerComplete(username, attestation);
}

export async function loginWithPasskey(username: string): Promise<void> {
  const { options } = await api.loginBegin(username);
  const assertion = await startAuthentication(options);
  await api.loginComplete(username, assertion);
}

/**
 * Step-up: prove the passkey again on the session that's already signed in.
 * Unlike login, this keeps the current session and cookie — it only refreshes
 * how recently the vault guard considers the user verified.
 */
export async function reverifyPasskey(): Promise<void> {
  const { options } = await api.reverifyBegin();
  const assertion = await startAuthentication(options);
  await api.reverifyComplete(assertion);
}

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

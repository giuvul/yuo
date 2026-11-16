// Session signals shared by the API client, the outbox and the root layout, without importing React.
// "Lost" means a request outside the sign-in routes came back 401: the session ended elsewhere (signed
// out, device revoked, expired). The layout listens and sends the learner to /sign-in.

type Listener = () => void;

const lostListeners = new Set<Listener>();

export function onSessionLost(listener: Listener): () => void {
  lostListeners.add(listener);
  return () => lostListeners.delete(listener);
}

export function sessionLost(): void {
  for (const l of lostListeners) l();
}

// The first-run wizard (code, credential, recovery codes) keeps the bare layout until the learner
// confirms the codes, although the install counts as enrolled as soon as the first credential exists.
let wizardActive = false;
const wizardListeners = new Set<Listener>();

export const setupWizard = {
  get: (): boolean => wizardActive,
  set(active: boolean): void {
    if (active === wizardActive) return;
    wizardActive = active;
    for (const l of wizardListeners) l();
  },
  subscribe(listener: Listener): () => void {
    wizardListeners.add(listener);
    return () => wizardListeners.delete(listener);
  },
};

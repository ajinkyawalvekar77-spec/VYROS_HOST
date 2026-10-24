const TEMPORARILY_DISABLED_MESSAGE =
  "Authentication is temporarily unavailable. Firebase sign-in has been disconnected.";

function isLocalDevelopmentHost() {
  const host = globalThis.location?.hostname;
  return ["localhost", "127.0.0.1", "::1"].includes(host);
}

function unavailableError() {
  const error = new Error(TEMPORARILY_DISABLED_MESSAGE);
  error.code = "auth/temporarily-disabled";
  return error;
}

async function unavailable() {
  throw unavailableError();
}

export const auth = {
  configured: import.meta.env.DEV
    && import.meta.env.VITE_ENABLE_LOCAL_DEMO_ACCESS === "true"
    && isLocalDevelopmentHost(),
  get localDevelopmentMode() {
    return this.configured;
  },
  enabled: false,
  currentUser: null,
  signIn: unavailable,
  signUp: unavailable,
  signInWithGoogle: unavailable,
  resendVerification: unavailable,
  refreshUser: unavailable,
  sendPasswordReset: unavailable,
  signOut: unavailable,
  getIdToken: unavailable,
};

export function authErrorMessage(error) {
  if (error?.code === "auth/temporarily-disabled") {
    return TEMPORARILY_DISABLED_MESSAGE;
  }
  return error?.message || "Authentication could not be completed. Please try again.";
}

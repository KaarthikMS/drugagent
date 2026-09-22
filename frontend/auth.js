/**
 * Cognito authentication: authorization code flow with PKCE.
 *
 * Hand-rolled rather than pulled from Amplify, for two reasons. The flow
 * is ~120 lines of standard OAuth, and Amplify Auth brings a large
 * dependency into a page whose entire job is to show text. Fewer moving
 * parts in front of health data is worth more than the convenience.
 *
 * TOKENS ARE HELD IN MEMORY ONLY. localStorage survives the tab and is
 * readable by any script that reaches the page, so an XSS there walks
 * away with an 8-hour token. Held in a module variable, a reload costs a
 * silent redirect through Cognito, which is cheap and leaves nothing
 * behind. The PKCE verifier does go to sessionStorage -- it must survive
 * exactly one redirect, and it is useless without the matching request.
 */

const CONFIG = window.APP_CONFIG || {};
const REDIRECT_URI = window.location.origin + window.location.pathname;

let idToken = null;
let expiresAt = 0;

// ---------------------------------------------------------------- PKCE

function randomString(bytes = 32) {
  const buf = new Uint8Array(bytes);
  crypto.getRandomValues(buf);
  return base64url(buf);
}

function base64url(bytes) {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function challengeFor(verifier) {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(verifier),
  );
  return base64url(new Uint8Array(digest));
}

// ------------------------------------------------------------- the flow

export async function signIn() {
  const verifier = randomString();
  const state = randomString(16);
  sessionStorage.setItem("pkce_verifier", verifier);
  sessionStorage.setItem("oauth_state", state);

  const params = new URLSearchParams({
    response_type: "code",
    client_id: CONFIG.clientId,
    redirect_uri: REDIRECT_URI,
    scope: "openid email profile",
    state,
    code_challenge: await challengeFor(verifier),
    code_challenge_method: "S256",
  });
  window.location.assign(`${CONFIG.hostedUi}/oauth2/authorize?${params}`);
}

export function signOut() {
  idToken = null;
  expiresAt = 0;
  const params = new URLSearchParams({
    client_id: CONFIG.clientId,
    logout_uri: REDIRECT_URI,
  });
  window.location.assign(`${CONFIG.hostedUi}/logout?${params}`);
}

/**
 * Complete a redirect back from Cognito, if this load is one.
 *
 * Returns true when a session was established. The code is exchanged
 * from the browser with no client secret -- which is why PKCE exists,
 * and why the app client is configured without one.
 */
export async function completeSignIn() {
  const url = new URL(window.location.href);
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  const error = url.searchParams.get("error");

  // Always clear the query, so a reload cannot replay the exchange and
  // an authorization code never sits in browser history.
  const clean = () => window.history.replaceState({}, "", REDIRECT_URI);

  if (error) {
    clean();
    throw new Error(url.searchParams.get("error_description") || error);
  }
  if (!code) return false;

  const expected = sessionStorage.getItem("oauth_state");
  const verifier = sessionStorage.getItem("pkce_verifier");
  sessionStorage.removeItem("oauth_state");
  sessionStorage.removeItem("pkce_verifier");
  clean();

  // A mismatched state means this redirect was not started by this tab.
  // Refusing it is what stops a forged login being stitched onto an
  // existing session.
  if (!expected || state !== expected || !verifier) {
    throw new Error("Sign-in could not be verified. Please try again.");
  }

  const res = await fetch(`${CONFIG.hostedUi}/oauth2/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      client_id: CONFIG.clientId,
      code,
      redirect_uri: REDIRECT_URI,
      code_verifier: verifier,
    }),
  });

  if (!res.ok) throw new Error("Sign-in failed.");

  const data = await res.json();
  idToken = data.id_token;
  // Expire a minute early, so a request is never sent with a token that
  // dies in flight.
  expiresAt = Date.now() + (data.expires_in - 60) * 1000;
  return true;
}

export function isSignedIn() {
  return Boolean(idToken) && Date.now() < expiresAt;
}

export function currentEmail() {
  if (!idToken) return null;
  try {
    // Read only. The signature is verified by API Gateway, which is the
    // only place a verification result may be trusted -- a browser
    // checking its own token proves nothing.
    const payload = idToken.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(atob(payload)).email || null;
  } catch {
    return null;
  }
}

/** Call the API with the current token. Redirects to sign-in on 401. */
export async function callApi(path, body) {
  if (!isSignedIn()) {
    await signIn();
    return null;
  }

  const res = await fetch(CONFIG.apiEndpoint + path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${idToken}`,
    },
    body: JSON.stringify(body),
  });

  if (res.status === 401) {
    idToken = null;
    await signIn();
    return null;
  }
  return res;
}

import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import {
  authConfig,
  clearToken,
  currentCaller,
  devSignIn,
  readToken,
  setUnauthorizedHandler,
  storeToken,
  type AuthConfig,
  type Caller,
} from "./api";

const VERIFIER_KEY = "case-file.pkce";
const STATE_KEY = "case-file.state";

function base64url(bytes: Uint8Array): string {
  let binary = "";
  bytes.forEach((value) => {
    binary += String.fromCharCode(value);
  });
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

async function sha256(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return base64url(new Uint8Array(digest));
}

export function SignIn() {
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const [subject, setSubject] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    authConfig()
      .then(setConfig)
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Sign-in is unavailable.");
      });
  }, []);

  async function onDev(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const issued = await devSignIn(subject.trim(), password);
      storeToken(issued.access_token);
      window.location.assign("/");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Sign-in was not accepted.");
      setBusy(false);
    }
  }

  async function onOidc() {
    if (!config?.authorization_endpoint || !config.client_id) {
      setError("The identity provider is not configured.");
      return;
    }
    const verifierBytes = new Uint8Array(32);
    crypto.getRandomValues(verifierBytes);
    const verifier = base64url(verifierBytes);
    const stateBytes = new Uint8Array(16);
    crypto.getRandomValues(stateBytes);
    const state = base64url(stateBytes);
    sessionStorage.setItem(VERIFIER_KEY, verifier);
    sessionStorage.setItem(STATE_KEY, state);
    const redirectUri = `${window.location.origin}/auth/callback`;
    const challenge = await sha256(verifier);
    const url = new URL(config.authorization_endpoint);
    url.searchParams.set("response_type", "code");
    url.searchParams.set("client_id", config.client_id);
    url.searchParams.set("redirect_uri", redirectUri);
    url.searchParams.set("scope", "openid profile");
    url.searchParams.set("code_challenge", challenge);
    url.searchParams.set("code_challenge_method", "S256");
    url.searchParams.set("state", state);
    if (config.audience) {
      url.searchParams.set("audience", config.audience);
    }
    window.location.assign(url.toString());
  }

  return (
    <main className="sign-in">
      <h1>Sign in</h1>
      <p className="quiet">Investigate only the services your company has granted you.</p>
      {config?.mode === "dev" ? (
        <form onSubmit={onDev} className="intake">
          <label>
            Subject
            <input value={subject} onChange={(event) => setSubject(event.target.value)} required autoComplete="username" />
          </label>
          <label>
            Password
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
              autoComplete="current-password"
            />
          </label>
          <button type="submit" disabled={busy}>
            Sign in
          </button>
        </form>
      ) : null}
      {config?.mode === "oidc" ? (
        <p className="actions">
          <button type="button" onClick={onOidc}>
            Continue with company login
          </button>
        </p>
      ) : null}
      {error ? <p className="problem">{error}</p> : null}
    </main>
  );
}

export function AuthCallback() {
  const started = useRef(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (started.current) {
      return;
    }
    started.current = true;
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const state = params.get("state");
    const expected = sessionStorage.getItem(STATE_KEY);
    const verifier = sessionStorage.getItem(VERIFIER_KEY);
    sessionStorage.removeItem(STATE_KEY);
    sessionStorage.removeItem(VERIFIER_KEY);
    if (!code || !verifier || !state || state !== expected) {
      setError("Sign-in was not accepted.");
      return;
    }
    authConfig()
      .then(async (config) => {
        if (!config.token_endpoint || !config.client_id) {
          throw new Error("The identity provider is not configured.");
        }
        const body = new URLSearchParams({
          grant_type: "authorization_code",
          code,
          redirect_uri: `${window.location.origin}/auth/callback`,
          client_id: config.client_id,
          code_verifier: verifier,
        });
        const response = await fetch(config.token_endpoint, {
          method: "POST",
          headers: { "content-type": "application/x-www-form-urlencoded" },
          body,
        });
        if (!response.ok) {
          throw new Error("Sign-in was not accepted.");
        }
        const issued = (await response.json()) as { access_token?: string };
        if (!issued.access_token) {
          throw new Error("Sign-in was not accepted.");
        }
        storeToken(issued.access_token);
        window.location.assign("/");
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Sign-in was not accepted.");
      });
  }, []);

  return (
    <main className="sign-in">
      <h1>Signing in</h1>
      {error ? <p className="problem">{error}</p> : <p className="quiet">Checking the company login.</p>}
    </main>
  );
}

export function useCaller(): Caller | null {
  const [caller, setCaller] = useState<Caller | null>(null);
  useEffect(() => {
    if (!readToken()) {
      return;
    }
    currentCaller()
      .then(setCaller)
      .catch(() => setCaller(null));
  }, []);
  return caller;
}

export function signOut() {
  clearToken();
  window.location.assign("/");
}

export function installUnauthorizedRedirect() {
  setUnauthorizedHandler(() => {
    if (window.location.pathname !== "/auth/callback") {
      window.location.assign("/");
    }
  });
}

export function RequireSignIn({ children }: { children: ReactNode }) {
  if (!readToken()) {
    return <SignIn />;
  }
  return children;
}

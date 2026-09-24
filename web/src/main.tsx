import { StrictMode, useEffect } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import { AuthCallback, RequireSignIn, installUnauthorizedRedirect, signOut, useCaller } from "./auth";
import { IncidentList } from "./IncidentList";
import { IncidentSheet } from "./IncidentSheet";
import "./styles.css";

function Shell() {
  const caller = useCaller();
  const scope = caller ? (caller.allows_all ? "All services" : caller.services.join(", ")) : "";
  return (
    <div className="app">
      <header className="top">
        <Link to="/" className="mark">
          Case file
        </Link>
        <div className="who">
          <p className="who-id">
            <span className="who-name">{caller ? caller.name : "Signed in"}</span>
            {scope ? <span className="who-scope">{scope}</span> : null}
          </p>
          <button type="button" className="sign-out" onClick={signOut}>
            Sign out
          </button>
        </div>
      </header>
      <div className="page">
        <Routes>
          <Route path="/" element={<IncidentList />} />
          <Route path="/incidents/:id" element={<IncidentSheet />} />
        </Routes>
      </div>
    </div>
  );
}

function App() {
  useEffect(() => {
    installUnauthorizedRedirect();
  }, []);
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/auth/callback" element={<AuthCallback />} />
        <Route
          path="/*"
          element={
            <RequireSignIn>
              <Shell />
            </RequireSignIn>
          }
        />
      </Routes>
    </BrowserRouter>
  );
}

const root = document.getElementById("root");
if (root) {
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}

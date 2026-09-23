import { StrictMode, useEffect } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import { AuthCallback, RequireSignIn, installUnauthorizedRedirect, signOut, useCaller } from "./auth";
import { IncidentList } from "./IncidentList";
import { IncidentSheet } from "./IncidentSheet";
import "./styles.css";

function Shell() {
  const caller = useCaller();
  return (
    <div className="page">
      <header className="top">
        <Link to="/" className="mark">
          Case file
        </Link>
        <p className="quiet who">
          {caller ? caller.name : "Signed in"}
          <button type="button" className="quiet-button" onClick={signOut}>
            Sign out
          </button>
        </p>
      </header>
      <Routes>
        <Route path="/" element={<IncidentList />} />
        <Route path="/incidents/:id" element={<IncidentSheet />} />
      </Routes>
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

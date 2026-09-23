import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import { IncidentList } from "./IncidentList";
import { IncidentSheet } from "./IncidentSheet";
import "./styles.css";

function App() {
  return (
    <BrowserRouter>
      <div className="page">
        <header className="top">
          <Link to="/" className="mark">
            Case file
          </Link>
          <p className="quiet">Investigations stay read-only until you mark a mitigation.</p>
        </header>
        <Routes>
          <Route path="/" element={<IncidentList />} />
          <Route path="/incidents/:id" element={<IncidentSheet />} />
        </Routes>
      </div>
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

import React from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { AuthProvider } from "./auth";
import RouteSeo from "./seo/RouteSeo";
import "./index.css";
import "@cbi/web-shared/styles/skeleton.css";

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <RouteSeo />
        <App />
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>,
);

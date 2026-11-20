import SiteScripts from "./components/SiteScripts";
import React from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { ThemeProvider } from "@cbi/web-shared/lib/theme";
import App from "./App";
import { AuthProvider } from "./auth";
import RouteSeo from "./seo/RouteSeo";
import "./index.css";
import "@cbi/web-shared/styles/skeleton.css";

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ThemeProvider>
      <BrowserRouter>
        <AuthProvider>
          <RouteSeo />
          <SiteScripts />
          <App />
        </AuthProvider>
      </BrowserRouter>
    </ThemeProvider>
  </React.StrictMode>,
);

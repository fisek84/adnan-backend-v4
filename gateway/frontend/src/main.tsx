// gateway/frontend/src/main.tsx

import React from "react";
import ReactDOM from "react-dom/client";

// style.css je u gateway/frontend/style.css, a ovaj fajl je u gateway/frontend/src/
// zato ide jedan nivo gore iz src/
import "../style.css";

import App from "./App";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

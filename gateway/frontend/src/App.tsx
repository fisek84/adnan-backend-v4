// gateway/frontend/src/App.tsx
import { CeoChatbox } from "./components/ceoChat/CeoChatbox";

export default function App() {
  return (
    <div style={{ height: "100vh" }}>
      <CeoChatbox ceoCommandUrl="/api/ceo-console/command" />
    </div>
  );
}

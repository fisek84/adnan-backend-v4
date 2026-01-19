// gateway/frontend/src/App.tsx
import { CeoChatbox } from "./components/ceoChat/CeoChatbox";

export default function App() {
  return (
    <div style={{ height: "100vh" }}>
      <CeoChatbox
        ceoCommandUrl="/api/chat"
        approveUrl="/api/ai-ops/approval/approve"
        executeRawUrl="/api/execute/raw"
        enableVoice={true}
        enableTTS={true}
        autoSpeak={false}
      />
    </div>
  );
}

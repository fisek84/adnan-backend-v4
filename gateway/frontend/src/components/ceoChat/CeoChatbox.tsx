// gateway/frontend/src/components/ceoChat/CeoChatbox.tsx
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  ChatItem,
  ChatMessageItem,
  GovernanceEventItem,
  NormalizedConsoleResponse,
  UiStrings,
} from "./types";
import { createCeoConsoleApi } from "./api";
import { defaultStrings } from "./strings";
import { useAutoScroll } from "./hooks";
import { useSpeechSynthesis } from "../../hooks/useSpeechSynthesis";
import {
  createAudioFromVoiceOutputUsingGlobals,
  extractVoiceOutputFromResponse,
  safeRevokeObjectUrl,
} from "../../utils/voiceOutputAudio";
import {
  BRIDGE_V1_GRACE_MS,
  shouldFireVoiceAutoSendAfterGrace,
  VOICE_AUTO_SEND_GRACE_MS,
} from "../../utils/voiceAutoSendGuards";
import { Header } from "../Header";
import { CommandPreviewModal } from "./CommandPreviewModal";
import "./CeoChatbox.css";

type CeoConsoleApi = ReturnType<typeof createCeoConsoleApi>;

type EnterpriseOpPatch = { op_id: string; changes: Record<string, any> };

type EnterprisePreviewGate = {
  patchesSig: string;
  canApprove: boolean;
  errors: number;
  dirty: boolean;
};

const enterprisePreviewEditorEnabled =
  String((import.meta as any)?.env?.VITE_ENTERPRISE_PREVIEW_EDITOR ?? "")
    .trim()
    .toLowerCase() === "true" ||
  String((import.meta as any)?.env?.VITE_ENTERPRISE_PREVIEW_EDITOR ?? "")
    .trim()
    .toLowerCase() === "1";

const uid = () =>
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `id_${Math.random().toString(16).slice(2)}_${Date.now()}`;

const now = () => Date.now();

const formatTime = (ms: number) => {
  const d = new Date(ms);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
};

type CeoChatboxProps = {
  ceoCommandUrl: string;
  approveUrl?: string; // POST { approval_id }
  rejectUrl?: string; // OPTIONAL: POST { approval_id } (if backend supports reject/deny)
  executeRawUrl?: string; // POST canonical proposal payload (opaque)
  headers?: Record<string, string>;
  strings?: Partial<UiStrings>;
  onOpenApprovals?: (approvalRequestId?: string) => void;
  className?: string;

  // Voice (client-side, no backend assumptions)
  enableVoice?: boolean; // default true
  autoSendOnVoiceFinal?: boolean; // default false
  enableTTS?: boolean; // default true - enable Text-to-Speech
  autoSpeak?: boolean; // default false - automatically speak system responses
  voiceLang?: string; // default 'en-US' - initial language for both STT and TTS
};

type BusyState = "idle" | "submitting" | "streaming" | "error";

// Notion Ops activation/deactivation commands
const NOTION_OPS_ACTIVATE_CMD = "notion ops aktiviraj";
const NOTION_OPS_DEACTIVATE_CMD = "notion ops ugasi";

const makeSystemProcessingItem = (requestId?: string): ChatMessageItem => ({
  id: uid(),
  kind: "message",
  role: "system",
  content: "",
  status: "streaming",
  createdAt: now(),
  requestId,
});

const toGovernanceCard = (resp: NormalizedConsoleResponse): GovernanceEventItem | null => {
  const gov = (resp as any)?.governance;
  if (!gov) return null;
  return {
    id: uid(),
    kind: "governance",
    createdAt: now(),
    state: gov.state,
    title: gov.title,
    summary: gov.summary,
    reasons: gov.reasons,
    approvalRequestId: gov.approvalRequestId,
    requestId: (resp as any)?.requestId,
  };
};

/**
 * CANON:
 * proposed_commands from /api/chat must be treated as an OPAQUE, ready-to-send execute/raw payload.
 * Frontend must NOT re-map/normalize/rebuild it (no command_type/payload transformations).
 */
type ProposedCmd = Record<string, any>;

const _extractProposedCommands = (resp: any): ProposedCmd[] => {
  const candidates = [
    resp?.proposed_commands,
    resp?.proposedCommands,
    resp?.raw?.proposed_commands,
    resp?.raw?.proposedCommands,
    resp?.result?.proposed_commands,
    resp?.result?.proposedCommands,
    resp?.governance?.proposed_commands,
    // FAZA A hardening: support camelCase under governance too
    resp?.governance?.proposedCommands,
  ];

  for (const c of candidates) {
    if (!Array.isArray(c)) continue;

    const out: ProposedCmd[] = [];
    for (const x of c) {
      if (!x || typeof x !== "object" || Array.isArray(x)) continue;
      out.push(x as ProposedCmd);
    }
    return out;
  }

  return [];
};

const _pickText = (x: any): string => {
  if (typeof x === "string") return x.trim();
  if (!x || typeof x !== "object") return "";
  const keys = ["summary", "text", "message", "output_text", "outputText", "detail"];
  for (const k of keys) {
    const v = (x as any)[k];
    if (typeof v === "string" && v.trim()) return v.trim();
  }
  return "";
};

function truncateText(s: string, maxLen = 20000): string {
  if (!s) return "";
  if (s.length <= maxLen) return s;
  return s.slice(0, maxLen) + "\n\n…(truncated)…";
}

function isAbortError(e: unknown): boolean {
  const msg = e instanceof Error ? e.message : String(e ?? "");
  return msg.toLowerCase().includes("aborted") || msg.toLowerCase().includes("abort");
}

/**
 * Render helper:
 * - Keeps plain-text rendering (no HTML injection)
 * - Makes "Open in Notion: https://..." clickable
 */
function renderTextWithNotionLink(text: string): React.ReactNode {
  const re = /(Open in Notion:\s*)(https?:\/\/\S+)/;
  const m = text.match(re);
  if (!m) return text;

  const prefix = m[1];
  const url = m[2];

  let safeUrl: string | null = null;
  try {
    safeUrl = new URL(url).toString();
  } catch {
    safeUrl = null;
  }

  const idx = text.indexOf(m[0]);
  const before = idx >= 0 ? text.slice(0, idx) : "";
  const after = idx >= 0 ? text.slice(idx + m[0].length) : "";

  return (
    <>
      {before}
      {prefix}
      {safeUrl ? (
        <a href={safeUrl} target="_blank" rel="noreferrer">
          {url}
        </a>
      ) : (
        url
      )}
      {after}
    </>
  );
}

type NotionLinkItem = {
  label: string;
  url: string;
};

function extractRefMapFromApproveResponse(res: any): Record<string, string> {
  const candidates = [
    res?.ref_map,
    res?.result?.ref_map,
    res?.result?.result?.ref_map,
    res?.raw?.ref_map,
  ];

  for (const c of candidates) {
    if (!c || typeof c !== "object" || Array.isArray(c)) continue;
    const out: Record<string, string> = {};
    for (const [k, v] of Object.entries(c)) {
      if (typeof k !== "string") continue;
      const val = typeof v === "string" ? v.trim() : "";
      if (!val) continue;
      out[k] = val;
    }
    return out;
  }

  return {};
}

function extractNotionLinksFromApproveResponse(res: any): NotionLinkItem[] {
  const out: NotionLinkItem[] = [];

  const list = res?.notion_urls;
  if (Array.isArray(list)) {
    for (const rec of list) {
      if (!rec || typeof rec !== "object") continue;
      const url = typeof rec.url === "string" ? rec.url.trim() : "";
      if (!url) continue;

      const opId = typeof rec.op_id === "string" ? rec.op_id.trim() : "";
      const intent = typeof rec.intent === "string" ? rec.intent.trim() : "";

      const label = opId && intent ? `${opId} (${intent})` : opId || intent || "Notion";
      out.push({ label, url });
    }
  }

  const byOp = res?.notion_urls_by_op_id;
  if (byOp && typeof byOp === "object" && !Array.isArray(byOp)) {
    const keys = Object.keys(byOp).sort();
    for (const k of keys) {
      const url = typeof byOp[k] === "string" ? String(byOp[k]).trim() : "";
      if (!url) continue;
      out.push({ label: k, url });
    }
  }

  // De-dupe by url
  const seen = new Set<string>();
  return out.filter((x) => {
    const u = x.url;
    if (seen.has(u)) return false;
    seen.add(u);
    return true;
  });
}

function NotionLinksPanel({ items }: { items: NotionLinkItem[] }) {
  if (!items.length) return null;

  return (
    <div style={{ marginTop: 10 }}>
      <div style={{ fontWeight: 700, marginBottom: 6 }}>Created in Notion</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {items.map((it) => (
          <div key={it.url} style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <span style={{ opacity: 0.85 }}>{it.label}:</span>
            <a href={it.url} target="_blank" rel="noreferrer">
              {it.url}
            </a>
          </div>
        ))}
      </div>
    </div>
  );
}

function RefMapPanel({ refMap }: { refMap: Record<string, string> }) {
  const keys = Object.keys(refMap || {}).sort();
  if (!keys.length) return null;

  return (
    <div style={{ marginTop: 10 }}>
      <div style={{ fontWeight: 700, marginBottom: 6 }}>Reference map</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {keys.map((k) => (
          <div key={k} style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <span style={{ opacity: 0.85 }}>{k}:</span>
            <span style={{ fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace" }}>
              {refMap[k]}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/**
 * IMPORTANT UX RULE (CANON):
 * Do NOT show "fallback proposals" (the ones that just echo a prompt / ceo.command.propose, dry_run).
 * Only hide proposals when the backend explicitly marks them as fallback.
 *
 * Production rule:
 * - NEVER infer fallback purely from command name (e.g. ceo.command.propose) + flags.
 * - Treat requires_approval as actionable; backend is the source of truth for validity.
 */
function isActionableProposal(p: ProposedCmd): boolean {
  if (!p || typeof p !== "object") return false;

  const cmd = typeof p.command === "string" ? p.command : "";
  const topIntent = typeof p.intent === "string" ? p.intent : "";
  const reason = typeof p.reason === "string" ? p.reason : "";

  // CANON: real intent can be nested at params.ai_command.intent for notion_write wrapper
  const nestedIntent =
    typeof (p as any)?.params?.ai_command?.intent === "string"
      ? (p as any).params.ai_command.intent
      : typeof (p as any)?.params?.aiCommand?.intent === "string"
        ? (p as any).params.aiCommand.intent
        : "";

  const intent = nestedIntent || topIntent;

  const dryRun = p.dry_run === true || p.dryRun === true;

  // Normalize "requires approval" flags (backend variations)
  const requiresApproval =
    p.requires_approval === true ||
    p.requiresApproval === true ||
    p.required_approval === true ||
    (p as any).requiredApproval === true;

  /**
   * CRITICAL FIX:
   * Contract no-op MUST be hidden when backend explicitly marks it.
   * This is NOT heuristics — it is an explicit backend marker.
   */
  const kind =
    typeof (p as any)?.payload_summary?.kind === "string" ? (p as any).payload_summary.kind : "";
  if (kind === "contract_noop") return false;

  /**
   * CRITICAL FIX:
   * Fallback MUST be recognized only via explicit backend marker in reason.
   * Do NOT use cmd/dryRun/requiresApproval heuristics to suppress proposals,
   * because ceo.command.propose may be the canonical wrapper.
   */
  const looksLikeFallback = /fallback proposal/i.test(reason);
  if (looksLikeFallback) return false;

  // If backend says it requires approval, it is actionable for UI purposes.
  // (Backend remains source-of-truth; execute/raw will validate.)
  if (requiresApproval) return true;

  const hasSomePayload =
    (p.args && typeof p.args === "object" && Object.keys(p.args).length > 0) ||
    (p.params && typeof p.params === "object" && Object.keys(p.params).length > 0) ||
    (p.payload && typeof p.payload === "object" && Object.keys(p.payload).length > 0);

  // If not approval-gated, avoid showing empty/no-op proposals.
  if (!intent && !hasSomePayload) return false;

  // Optional: keep dryRun proposals visible only if they have explicit intent/payload.
  void cmd;
  void dryRun;

  return true;
}

function proposalLabel(p: ProposedCmd, idx: number): string {
  const cmd = typeof (p as any)?.command === "string" ? (p as any).command : "";
  const topIntent = typeof (p as any)?.intent === "string" ? (p as any).intent : "";
  const commandType = typeof (p as any)?.command_type === "string" ? (p as any).command_type : "";

  // CANON: show ai_command.intent for notion_write wrapper
  const nestedIntent =
    typeof (p as any)?.params?.ai_command?.intent === "string"
      ? (p as any).params.ai_command.intent
      : typeof (p as any)?.params?.aiCommand?.intent === "string"
        ? (p as any).params.aiCommand.intent
        : "";

  if (nestedIntent) return nestedIntent;
  if (topIntent) return topIntent;
  if (cmd) return cmd;
  if (commandType) return commandType;
  return `proposal_${idx + 1}`;
}

function shouldShowBackendGovernanceCard(gov: GovernanceEventItem, actionableCount: number): boolean {
  if (!gov) return false;

  const title = (gov.title ?? "").toLowerCase();
  const state = (gov as any)?.state ?? "";

  const isProposalReadyCard =
    title.includes("proposals ready") || title.includes("proposed commands") || title.includes("proposal");

  if (isProposalReadyCard && state === "BLOCKED" && !gov.approvalRequestId && actionableCount === 0) {
    return false;
  }

  return true;
}

/** SpeechRecognition typings (browser) */
declare global {
  interface Window {
    webkitSpeechRecognition?: any;
    SpeechRecognition?: any;

    AdnanBridgeV1?: {
      nativeHello: (payload: any) => { ok: true } | { ok: false; reason: string };
      submitFinalTranscript: (payload: any) => { ok: true } | { ok: false; reason: string };
      updatePartialTranscript?: (payload: any) => { ok: true } | { ok: false; reason: string };
    };
  }
}

export const CeoChatbox: React.FC<CeoChatboxProps> = ({
  ceoCommandUrl,
  approveUrl,
  rejectUrl,
  executeRawUrl,
  headers,
  strings,
  onOpenApprovals,
  className,
  enableVoice = true,
  autoSendOnVoiceFinal = false,
  enableTTS = true,
  autoSpeak = false,
  voiceLang = 'en-US',
}) => {
  const ui = useMemo(() => ({ ...defaultStrings, ...(strings ?? {}) }), [strings]);

  const effectiveApproveUrl = approveUrl?.trim() ? approveUrl : "/api/ai-ops/approval/approve";
  const effectiveRejectUrl = rejectUrl?.trim() ? rejectUrl : "/api/ai-ops/approval/reject";

  const api: CeoConsoleApi = useMemo(
    () =>
      (createCeoConsoleApi as any)({
        ceoCommandUrl,
        approveUrl: effectiveApproveUrl,
        headers,
      }) as CeoConsoleApi,
    [ceoCommandUrl, effectiveApproveUrl, headers]
  );

  const [items, setItems] = useState<ChatItem[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState<BusyState>("idle");
  const [lastError, setLastError] = useState<string | null>(null);

  // Keep current busy state accessible to bridge callbacks/timers.
  const busyRef = useRef<BusyState>("idle");
  useEffect(() => {
    busyRef.current = busy;
  }, [busy]);

  // Voice / TTS settings (with localStorage persistence)
  const [currentVoiceLang, setCurrentVoiceLang] = useState<string>(() => {
    if (typeof window === 'undefined') return voiceLang || 'en-US';
    try {
      const stored = localStorage.getItem('ceo_voice_lang');
      if (stored) return stored;
    } catch {
      // ignore
    }
    return voiceLang || 'en-US';
  });

  const [voiceEnabled, setVoiceEnabled] = useState<boolean>(() => {
    if (typeof window === 'undefined') return enableVoice;
    try {
      const stored = localStorage.getItem('ceo_voice_enabled');
      if (stored === 'true') return true;
      if (stored === 'false') return false;
    } catch {}
    return enableVoice;
  });

  const [ttsEnabled, setTtsEnabled] = useState<boolean>(() => {
    if (typeof window === 'undefined') return enableTTS;
    try {
      const stored = localStorage.getItem('ceo_tts_enabled');
      if (stored === 'true') return true;
      if (stored === 'false') return false;
    } catch {}
    return enableTTS;
  });

  const [autoSpeakEnabled, setAutoSpeakEnabled] = useState<boolean>(() => {
    if (typeof window === 'undefined') return autoSpeak;
    try {
      const stored = localStorage.getItem('ceo_auto_speak');
      if (stored === 'true') return true;
      if (stored === 'false') return false;
    } catch {}
    return autoSpeak;
  });

  const [autoSendOnVoiceFinalEnabled, setAutoSendOnVoiceFinalEnabled] = useState<boolean>(() => {
    if (typeof window === 'undefined') return autoSendOnVoiceFinal;
    try {
      const stored = localStorage.getItem('ceo_auto_send_voice');
      if (stored === 'true') return true;
      if (stored === 'false') return false;
    } catch {}
    return autoSendOnVoiceFinal;
  });

  const [speechRate, setSpeechRate] = useState<number>(() => {
    if (typeof window === 'undefined') return 1.0;
    try {
      const stored = localStorage.getItem('ceo_speech_rate');
      if (stored) {
        const v = parseFloat(stored);
        if (!Number.isNaN(v) && v > 0.5 && v < 2.0) return v;
      }
    } catch {}
    return 1.0;
  });

  const [speechPitch, setSpeechPitch] = useState<number>(() => {
    if (typeof window === 'undefined') return 1.0;
    try {
      const stored = localStorage.getItem('ceo_speech_pitch');
      if (stored) {
        const v = parseFloat(stored);
        if (!Number.isNaN(v) && v > 0.5 && v < 2.0) return v;
      }
    } catch {}
    return 1.0;
  });

  const [outputLanguage, setOutputLanguage] = useState<string>(() => {
    if (typeof window === 'undefined') return 'bs';
    try {
      const stored = localStorage.getItem('ceo_output_lang');
      if (stored === 'en' || stored === 'bs' || stored === 'hr' || stored === 'sr' || stored === 'de') return stored;
    } catch {}
    return 'bs';
  });

  // Backend voice profiles (per-agent) — persisted client-side, resolved server-side.
  type BackendVoiceProfile = {
    language?: string;
    gender?: string;
    preset_id?: string;
  };

  type BackendVoicePreset = {
    preset_id: string;
    label: string;
    vendor_voice: string;
    gender: string;
    languages: string[];
  };

  type BackendVoiceProfilesResponse = {
    provider?: { type?: string; configured?: boolean; enabled?: boolean };
    catalog?: {
      supported_languages?: string[];
      supported_genders?: string[];
      presets?: BackendVoicePreset[];
    };
    agents?: { agent_id: string; name: string }[];
  };

  const [backendVoiceAgents, setBackendVoiceAgents] = useState<{ agent_id: string; name: string }[]>([]);
  const [backendVoicePresets, setBackendVoicePresets] = useState<BackendVoicePreset[]>([]);

  const [voiceProfileTargetAgentId, setVoiceProfileTargetAgentId] = useState<string>(() => {
    if (typeof window === 'undefined') return 'ceo_advisor';
    try {
      const stored = localStorage.getItem('ceo_backend_voice_target_agent');
      if (stored && stored.trim()) return stored;
    } catch {}
    return 'ceo_advisor';
  });

  const [backendVoiceProfiles, setBackendVoiceProfiles] = useState<Record<string, BackendVoiceProfile>>(() => {
    if (typeof window === 'undefined') return {};
    try {
      const raw = localStorage.getItem('ceo_backend_voice_profiles_v1');
      if (!raw) return {};
      const obj = JSON.parse(raw);
      return obj && typeof obj === 'object' ? obj : {};
    } catch {
      return {};
    }
  });

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      try {
        const res = await fetch('/api/voice/profiles', { method: 'GET' });
        if (!res.ok) return;
        const data = (await res.json()) as BackendVoiceProfilesResponse;
        if (cancelled) return;
        const agents = Array.isArray(data?.agents) ? data.agents : [];
        const presets = Array.isArray(data?.catalog?.presets) ? data.catalog!.presets! : [];
        setBackendVoiceAgents(agents);
        setBackendVoicePresets(presets);
      } catch {
        // ignore (UI should still work with stored selections)
      }
    };
    void run();
    return () => {
      cancelled = true;
    };
  }, []);
  
  // Session ID for Notion ops tracking
  const [sessionId] = useState<string>(() => {
    // Try to restore from sessionStorage, or create new
    const stored = typeof sessionStorage !== 'undefined' ? sessionStorage.getItem('ceo_chat_session_id') : null;
    if (stored) return stored;
    
    const newId = `session_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;
    if (typeof sessionStorage !== 'undefined') {
      sessionStorage.setItem('ceo_chat_session_id', newId);
    }
    return newId;
  });
  
  // Notion ops armed state - restore from sessionStorage
  const [notionOpsArmed, setNotionOpsArmed] = useState<boolean>(() => {
    if (typeof sessionStorage !== 'undefined') {
      const stored = sessionStorage.getItem('notion_ops_armed');
      return stored === 'true';
    }
    return false;
  });

  const abortRef = useRef<AbortController | null>(null);
  const previewAbortRef = useRef<AbortController | null>(null);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);

  // Track whether the current draft was last produced by voice recognition.
  // This lets us route dictation submits through /api/voice/exec_text without touching typed flow.
  const lastDraftFromVoiceRef = useRef(false);

  // Track created ObjectURLs so we can revoke them (avoid leaks).
  const audioUrlByMsgIdRef = useRef<Map<string, string>>(new Map());

  // Track currently playing backend audio (autoplay / stop support).
  const backendAudioRef = useRef<HTMLAudioElement | null>(null);

  const stopBackendAudio = useCallback(() => {
    const a = backendAudioRef.current;
    if (!a) return;
    try {
      a.pause();
    } catch {
      // ignore
    }
    backendAudioRef.current = null;
  }, []);

  const tryAutoplayBackendAudioUrl = useCallback(
    async (url: string): Promise<boolean> => {
      if (!url) return false;
      stopBackendAudio();
      try {
        const a = new Audio(url);
        a.preload = "auto";
        backendAudioRef.current = a;
        await a.play();
        return true;
      } catch {
        return false;
      }
    },
    [stopBackendAudio]
  );

  useEffect(() => {
    return () => {
      // On unmount, revoke all ObjectURLs we created.
      for (const url of audioUrlByMsgIdRef.current.values()) safeRevokeObjectUrl(url);
      audioUrlByMsgIdRef.current.clear();

      // Stop any in-flight backend audio playback.
      stopBackendAudio();
    };
  }, [stopBackendAudio]);

  const resizeComposer = useCallback(() => {
    const el = composerRef.current;
    if (!el) return;
    // Reset first so scrollHeight recomputes correctly
    el.style.height = "0px";
    const max = 180;
    const next = Math.min(el.scrollHeight || 0, max);
    el.style.height = `${Math.max(next, 24)}px`;
    el.style.overflowY = (el.scrollHeight || 0) > max ? "auto" : "hidden";
  }, []);

  useEffect(() => {
    resizeComposer();
  }, [draft, resizeComposer]);

  // Text-to-Speech hook with configured language (Bosanski / English)
  const {
    speak,
    cancel: cancelSpeech,
    speaking,
    supported: ttsSupported,
    voices,
    selectedVoiceName,
    selectVoiceByName,
  } = useSpeechSynthesis(currentVoiceLang, { rate: speechRate, pitch: speechPitch });

  const voiceLangOptions = useMemo(
    () => [
      { value: 'en-US', label: 'English' },
      { value: 'bs-BA', label: 'Bosanski' },
    ],
    []
  );

  const ttsVoiceOptions = useMemo(() => {
    if (!voices || voices.length === 0) return [] as { value: string; label: string }[];
    const langLower = currentVoiceLang.toLowerCase();
    let prefixes = [langLower.slice(0, 2)];
    if (langLower.startsWith("bs") || langLower.startsWith("hr") || langLower.startsWith("sr")) {
      prefixes = ["bs", "hr", "sr", "sh"];
    }

    // First, collect voices that best match the current language (recommended),
    // then append all remaining voices so the user can pick English / British,
    // male/female variants even when using Bosnian UI.
    const tagged = voices.map((v, index) => ({ voice: v, index }));
    const primary = tagged.filter(({ voice }) => {
      const vlang = voice.lang?.toLowerCase() || "";
      return prefixes.some((p) => vlang.startsWith(p));
    });
    const primarySet = new Set(primary.map((x) => x.index));
    const others = tagged.filter((x) => !primarySet.has(x.index));
    const ordered = [...primary, ...others];

    return ordered.map(({ voice, index }) => {
      const vlang = voice.lang?.toLowerCase() || "";
      const isPrimary = prefixes.some((p) => vlang.startsWith(p));
      const baseName = voice.name || `Voice ${index + 1}`;
      const labelCore = `${baseName}${voice.lang ? ` (${voice.lang})` : ''}`;
      return {
        value: voice.name || `voice-${index}`,
        label: isPrimary ? `⭐ ${labelCore}` : labelCore,
      };
    });
  }, [voices, currentVoiceLang]);

  const { viewportRef, isPinnedToBottom, scrollToBottom } = useAutoScroll();

  useEffect(() => {
    if (isPinnedToBottom) scrollToBottom(false);
  }, [items.length, isPinnedToBottom, scrollToBottom]);

  const appendItem = useCallback((it: ChatItem) => {
    setItems((prev) => [...prev, it]);
  }, []);

  const updateItem = useCallback((id: string, patch: Partial<ChatItem>) => {
    setItems((prev) => prev.map((x) => (x.id === id ? ({ ...x, ...(patch as any) } as ChatItem) : x)));
  }, []);

  useEffect(() => {
    // Revoke ObjectURLs for messages that are no longer present.
    const liveIds = new Set(items.map((it) => it.id));
    for (const [id, url] of audioUrlByMsgIdRef.current.entries()) {
      if (!liveIds.has(id)) {
        safeRevokeObjectUrl(url);
        audioUrlByMsgIdRef.current.delete(id);
      }
    }
  }, [items]);

  const removeItem = useCallback((id: string) => {
    setItems((prev) => prev.filter((x) => x.id !== id));
  }, []);

  const stopCurrent = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    previewAbortRef.current?.abort();
    previewAbortRef.current = null;
    cancelSpeech();
    stopBackendAudio();
    setBusy("idle");
  }, [cancelSpeech, stopBackendAudio]);

  // --- URL resolver (resolve a specific API path against a configurable base URL) ---
  // IMPORTANT: For endpoints like /api/execute/preview we must NOT reuse the base URL path
  // (e.g. a configured executeRawUrl pointing at /api/execute/raw). Always resolve the path.
  const resolveEndpoint = useCallback(
    (baseUrl: string | undefined, path: string): string => {
      try {
        const base = baseUrl && baseUrl.trim() ? new URL(baseUrl, ceoCommandUrl).toString() : ceoCommandUrl;
        return new URL(path, base).toString();
      } catch {
        // Fail-soft fallback: if URL parsing fails, at least return the path.
        return path;
      }
    },
    [ceoCommandUrl]
  );

  const mergedHeaders = useMemo(() => {
    return {
      "Content-Type": "application/json",
      // Backend CEO detection relies on this header for browser requests.
      // Keep it defaulted here so CEO-only endpoints (e.g. /api/notion-ops/toggle)
      // work even if caller didn't pass custom headers.
      "X-Initiator": "ceo_chat",
      ...(headers ?? {}),
    } as Record<string, string>;
  }, [headers]);

  const postJson = useCallback(
    async (url: string, body: any, signal: AbortSignal): Promise<any> => {
      const res = await fetch(url, {
        method: "POST",
        headers: mergedHeaders,
        body: JSON.stringify(body ?? {}),
        signal,
      });
      const txt = await res.text();
      if (!res.ok) throw new Error(`${url} failed (${res.status}): ${txt || "no body"}`);
      try {
        return txt ? JSON.parse(txt) : {};
      } catch {
        const head = (txt || "").slice(0, 800);
        throw new Error(`${url} returned non-JSON response: ${head || "<empty>"}`);
      }
    },
    [mergedHeaders]
  );

  // ------------------------------
  // PREVIEW (no approvals)
  // ------------------------------
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewData, setPreviewData] = useState<any>(null);
  const [previewTitle, setPreviewTitle] = useState<string>("Preview");

  const [previewProposal, setPreviewProposal] = useState<ProposedCmd | null>(null);
  const [previewProposalLabel, setPreviewProposalLabel] = useState<string | undefined>(undefined);
  const [previewProposalKey, setPreviewProposalKey] = useState<string | null>(null);
  const [proposalPatches, setProposalPatches] = useState<Record<string, Record<string, any>>>({});
  const [proposalEnterprisePatches, setProposalEnterprisePatches] = useState<
    Record<string, EnterpriseOpPatch[]>
  >({});
  const [enterprisePreviewGateByKey, setEnterprisePreviewGateByKey] = useState<
    Record<string, EnterprisePreviewGate>
  >({});

  const stableStringify = useCallback((value: any): string => {
    const seen = new WeakSet<object>();
    const norm = (v: any): any => {
      if (v === null || v === undefined) return v;
      if (typeof v !== "object") return v;
      if (seen.has(v)) return "[Circular]";
      seen.add(v);
      if (Array.isArray(v)) return v.map(norm);
      const out: any = {};
      for (const k of Object.keys(v).sort()) out[k] = norm(v[k]);
      return out;
    };
    try {
      return JSON.stringify(norm(value));
    } catch {
      return String(value);
    }
  }, []);

  const getProposalKey = useCallback(
    (proposal: ProposedCmd, _label?: string): string => {
      const intent = (proposal as any)?.intent ?? (proposal as any)?.command ?? "";
      const prompt = (proposal as any)?.params?.prompt ?? (proposal as any)?.metadata?.prompt ?? "";
      const aiIntent = (proposal as any)?.params?.ai_command?.intent ?? "";
      return stableStringify({ intent, prompt, ai_intent: aiIntent });
    },
    [stableStringify]
  );

  const applyPatchToProposal = useCallback((proposal: ProposedCmd, patch: Record<string, any> | undefined): ProposedCmd => {
    if (!patch || typeof patch !== "object" || Object.keys(patch).length === 0) return proposal;
    const paramsIn = (proposal as any)?.params;
    const params = paramsIn && typeof paramsIn === "object" ? { ...paramsIn } : {};
    for (const [k, v] of Object.entries(patch)) params[k] = v;
    return { ...(proposal as any), params } as any;
  }, []);

  // Shared helper for sending a chat message from arbitrary text.
  // Used both by the manual composer (submit) and voice auto-send.
  const sendChatFromText = async (rawText: string, opts?: { origin?: "voice" | "text" }) => {
    const trimmed = rawText.trim();
    if (!trimmed) return;
    if (busy === "submitting" || busy === "streaming") return;

    setBusy("submitting");
    setLastError(null);

    const clientRequestId = uid();

    const ceoItem: ChatMessageItem = {
      id: uid(),
      kind: "message",
      role: "ceo",
      content: trimmed,
      status: "delivered",
      createdAt: now(),
      requestId: clientRequestId,
    };

    appendItem(ceoItem);
    setDraft("");

    const placeholder = makeSystemProcessingItem(clientRequestId);
    appendItem(placeholder);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const agentId = notionOpsArmed ? "notion_ops" : "ceo_advisor";

      const req: any = {
        message: trimmed,
        text: trimmed,
        input_text: trimmed,

        initiator: "ceo_chat",
        session_id: sessionId,  // Also include at top level for compatibility
        source: "ceo_dashboard",
        preferred_agent_id: agentId,
        output_lang: outputLanguage,
        
        // CRITICAL: metadata with session_id per test protocol
        metadata: {
          session_id: sessionId,
          initiator: "ceo_chat",
          ui_output_lang: outputLanguage,
        },
        
        context_hint: {
          preferred_agent_id: agentId,
          ui_output_lang: outputLanguage,
        },
      };

      // Backend voice_output is only available when routing through the voice adapter.
      // Today we do that for dictation (origin=voice). When the user explicitly enables
      // TTS, route through the voice adapter as well so the UX can prefer backend audio.
      const origin =
        opts?.origin ??
        (ttsEnabled ? "voice" : lastDraftFromVoiceRef.current ? "voice" : "text");

      if (origin === 'voice' && ttsEnabled) {
        const vp = backendVoiceProfiles && typeof backendVoiceProfiles === 'object' ? backendVoiceProfiles : {};
        if (Object.keys(vp).length > 0) {
          req.metadata = req.metadata && typeof req.metadata === 'object' ? req.metadata : {};
          req.metadata.voice_profiles = vp;
        }
      }
      // Once submitted, clear the origin marker.
      lastDraftFromVoiceRef.current = false;

      const resp =
        origin === "voice"
          ? await api.sendVoiceExecText(req, controller.signal)
          : await api.sendCommand(req, controller.signal);
      
      // Check if Notion ops state changed (per test: resp.notion_ops.armed)
      const notionOps = (resp as any)?.raw?.notion_ops || (resp as any)?.notion_ops;
      if (notionOps && typeof notionOps.armed === 'boolean') {
        setNotionOpsArmed(notionOps.armed);
        
        // Store armed state in sessionStorage for persistence
        if (typeof sessionStorage !== 'undefined') {
          sessionStorage.setItem('notion_ops_armed', notionOps.armed ? 'true' : 'false');
        }
      }

      abortRef.current = null;
      try {
        await flushResponseToUi(placeholder.id, resp);
      } catch (e) {
        // If streaming fails to parse/consume, fallback to non-streaming.
        // - Chat streaming: fallback to canonical JSON /api/chat.
        // - Voice realtime WS streaming: fallback to HTTP /api/voice/exec_text.
        // Never fallback on abort.
        if (!isAbortError(e) && (resp as any)?.stream) {
          if (origin === "voice") {
            try {
              const fallback = await api.sendVoiceExecText(req, controller.signal, {
                forceHttp: true,
              });
              await flushResponseToUi(placeholder.id, fallback);
              setBusy("idle");
              setLastError(null);
              return;
            } catch {
              // Last-resort safety: if voice endpoints are unavailable, fall back to canonical chat.
              const fallbackChat = await api.sendCommand(req, controller.signal, undefined, {
                forceNonStreaming: true,
              });
              await flushResponseToUi(placeholder.id, fallbackChat);
              setBusy("idle");
              setLastError(null);
              return;
            }
          }

          const fallback = await api.sendCommand(req, controller.signal, undefined, {
            forceNonStreaming: true,
          });
          await flushResponseToUi(placeholder.id, fallback);
          setBusy("idle");
          setLastError(null);
          return;
        }
        throw e;
      }

      setBusy("idle");
      setLastError(null);
    } catch (e) {
      abortRef.current = null;
      const msg = e instanceof Error ? e.message : String(e);
      updateItem(placeholder.id, { status: "error", content: "" });
      setBusy(isAbortError(e) ? "idle" : "error");
      setLastError(isAbortError(e) ? null : msg);
    }
  };

  // ------------------------------
  // iOS WKWebView Bridge V1 (native STT -> web send)
  // Contract:
  // - window.AdnanBridgeV1
  // - nativeHello() activates bridge
  // - submitFinalTranscript() arms grace timer and sends via sendChatFromText(..., {origin:"voice"})
  // - updatePartialTranscript() cancels pending grace timer (optional UI draft update)
  // No DOM injection; explicit API only.
  // ------------------------------
  type BridgeResultV1 =
    | { ok: true }
    | { ok: false; reason: "bridge_not_ready" | "invalid_payload" | "duplicate_utterance" | "busy" };

  type NativeHelloPayloadV1 = {
    bridgeVersion: 1;
    runtime: "ios_wkwebview";
    appBuild?: string;
    deviceLocale?: string;
  };

  type UpdatePartialTranscriptPayloadV1 = {
    utteranceId: string;
    text: string;
    lang?: string;
    capturedAtMs?: number;
  };

  type SubmitFinalTranscriptPayloadV1 = {
    utteranceId: string;
    text: string;
    lang?: string;
    capturedAtMs?: number;
  };

  const bridgeReadyRef = useRef<boolean>(false);
  const bridgeSentUtterancesRef = useRef<Set<string>>(new Set());
  const bridgeTimersByUtteranceRef = useRef<Map<string, number>>(new Map());
  const sendChatFromTextRef = useRef(sendChatFromText);
  sendChatFromTextRef.current = sendChatFromText;

  const clearBridgeTimerForUtterance = useCallback((utteranceId: string) => {
    const t = bridgeTimersByUtteranceRef.current.get(utteranceId);
    if (t == null) return;
    try {
      window.clearTimeout(t);
    } catch {
      // ignore
    }
    bridgeTimersByUtteranceRef.current.delete(utteranceId);
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;

    const bridge: Window["AdnanBridgeV1"] = {
      nativeHello: (payload: NativeHelloPayloadV1): BridgeResultV1 => {
        if (!payload || typeof payload !== "object") return { ok: false, reason: "invalid_payload" };
        if (payload.bridgeVersion !== 1) return { ok: false, reason: "invalid_payload" };
        if (payload.runtime !== "ios_wkwebview") return { ok: false, reason: "invalid_payload" };
        bridgeReadyRef.current = true;
        return { ok: true };
      },

      submitFinalTranscript: (payload: SubmitFinalTranscriptPayloadV1): BridgeResultV1 => {
        if (!bridgeReadyRef.current) return { ok: false, reason: "bridge_not_ready" };
        if (!payload || typeof payload !== "object") return { ok: false, reason: "invalid_payload" };
        const utteranceId = typeof payload.utteranceId === "string" ? payload.utteranceId.trim() : "";
        const text = typeof payload.text === "string" ? payload.text.trim() : "";
        if (!utteranceId || !text) return { ok: false, reason: "invalid_payload" };

        const b = busyRef.current;
        if (b === "submitting" || b === "streaming") return { ok: false, reason: "busy" };

        if (bridgeSentUtterancesRef.current.has(utteranceId)) {
          return { ok: false, reason: "duplicate_utterance" };
        }

        // Re-arm grace timer for this utterance.
        clearBridgeTimerForUtterance(utteranceId);
        const timer = window.setTimeout(() => {
          bridgeTimersByUtteranceRef.current.delete(utteranceId);

          // Re-check busy at fire time; if busy, do not send and allow native to retry.
          const b2 = busyRef.current;
          if (b2 === "submitting" || b2 === "streaming") return;

          if (bridgeSentUtterancesRef.current.has(utteranceId)) return;
          bridgeSentUtterancesRef.current.add(utteranceId);

          // Mark as voice-origin and send via canonical helper.
          lastDraftFromVoiceRef.current = true;
          void sendChatFromTextRef.current(text, { origin: "voice" });
        }, BRIDGE_V1_GRACE_MS);

        bridgeTimersByUtteranceRef.current.set(utteranceId, timer);
        return { ok: true };
      },

      updatePartialTranscript: (payload: UpdatePartialTranscriptPayloadV1): BridgeResultV1 => {
        if (!bridgeReadyRef.current) return { ok: false, reason: "bridge_not_ready" };
        if (!payload || typeof payload !== "object") return { ok: false, reason: "invalid_payload" };
        const utteranceId = typeof payload.utteranceId === "string" ? payload.utteranceId.trim() : "";
        const text = typeof payload.text === "string" ? payload.text : "";
        if (!utteranceId) return { ok: false, reason: "invalid_payload" };

        // Any partial update cancels a pending send.
        clearBridgeTimerForUtterance(utteranceId);

        // Optional: reflect partial transcript in UI draft (no sending).
        const next = text.trim();
        if (next) {
          lastDraftFromVoiceRef.current = true;
          setDraft(next);
        } else if (lastDraftFromVoiceRef.current) {
          // Allow native to clear its own draft without nuking typed text.
          setDraft("");
        }
        return { ok: true };
      },
    };

    const prev = window.AdnanBridgeV1;
    window.AdnanBridgeV1 = bridge;

    return () => {
      // Cleanup timers and restore previous bridge if we replaced it.
      for (const t of bridgeTimersByUtteranceRef.current.values()) {
        try {
          window.clearTimeout(t);
        } catch {
          // ignore
        }
      }
      bridgeTimersByUtteranceRef.current.clear();

      if (window.AdnanBridgeV1 === bridge) {
        window.AdnanBridgeV1 = prev;
      }
    };
  }, [BRIDGE_V1_GRACE_MS, clearBridgeTimerForUtterance, setDraft]);

  const handlePreviewProposal = useCallback(
    async (proposal: ProposedCmd, label?: string, patchesOverride?: EnterpriseOpPatch[]) => {
      if (previewLoading) return;

      setPreviewOpen(true);
      setPreviewTitle(label ? `Preview: ${label}` : "Preview");
      setPreviewLoading(true);
      setPreviewError(null);
      setPreviewData(null);

      setPreviewProposal(proposal);
      setPreviewProposalLabel(label);
      const key = getProposalKey(proposal, label);
      setPreviewProposalKey(key);

      const controller = new AbortController();
      previewAbortRef.current = controller;

      try {
        const proposalWithSession = {
          ...proposal,
          metadata: {
            ...(proposal.metadata || {}),
            session_id: sessionId,
            source: "ceo_dashboard",
          },
        };

        const previewUrl = resolveEndpoint(executeRawUrl, "/api/execute/preview");
        if (enterprisePreviewEditorEnabled) {
          const patches = Array.isArray(patchesOverride)
            ? (patchesOverride as EnterpriseOpPatch[])
            : (proposalEnterprisePatches[key] || []);
          const patchesSig = stableStringify(patches);
          const json = await postJson(
            previewUrl,
            { ...proposalWithSession, patches },
            controller.signal,
          );
          setPreviewData(json);

          // Capture approval gating info for this proposal key.
          const notion = (json as any)?.notion;
          const v = notion && typeof notion === "object" ? (notion as any).validation : null;
          const summary = v && typeof v === "object" ? v.summary : null;
          const errs = summary && typeof summary === "object" ? Number(summary.errors || 0) : 0;
          const canApprove = Boolean(v && typeof v === "object" ? v.can_approve : true);
          setEnterprisePreviewGateByKey((prev) => ({
            ...prev,
            [key]: {
              patchesSig,
              canApprove,
              errors: Number.isFinite(errs) ? errs : 0,
              dirty: false,
            },
          }));
        } else {
          const patch = proposalPatches[key];
          const patched = applyPatchToProposal(proposalWithSession, patch);
          const json = await postJson(previewUrl, patched, controller.signal);
          setPreviewData(json);
        }
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        setPreviewError(msg);
      } finally {
        previewAbortRef.current = null;
        setPreviewLoading(false);
      }
    },
    [
      applyPatchToProposal,
      executeRawUrl,
      getProposalKey,
      postJson,
      previewLoading,
      stableStringify,
      proposalEnterprisePatches,
      proposalPatches,
      resolveEndpoint,
      sessionId,
    ]
  );

  // ------------------------------
  // VOICE INPUT (browser STT)
  // ------------------------------
  const [voiceSupported, setVoiceSupported] = useState(false);
  const [listening, setListening] = useState(false);
  const recognitionRef = useRef<any>(null);

  // Natural auto-send:
  // - do NOT trigger on first isFinal
  // - arm a grace timer on `onend`
  const voiceLastFinalRef = useRef<string>("");
  const voiceLastResultAtMsRef = useRef<number>(0);
  const autoSendGraceTimerRef = useRef<number | null>(null);
  const autoSendSessionRef = useRef<number>(0);
  const autoSendSentForSessionRef = useRef<number>(-1);

  // iOS WebViews frequently present a Safari-like UA; we must NOT disable auto-send
  // purely by UA. We use this only to enable an additional behavior-based fallback.
  const isIosDevice = useCallback((): boolean => {
    if (typeof navigator === "undefined") return false;
    const ua = String(navigator.userAgent || "");
    return /iP(hone|ad|od)/.test(ua);
  }, []);

  const clearAutoSendGraceTimer = useCallback(() => {
    if (autoSendGraceTimerRef.current == null) return;
    try {
      window.clearTimeout(autoSendGraceTimerRef.current);
    } catch {
      // ignore
    }
    autoSendGraceTimerRef.current = null;
  }, []);

  useEffect(() => {
    if (!voiceEnabled) return;

    const Rec = window.SpeechRecognition || window.webkitSpeechRecognition;
    const ok = typeof Rec === "function";
    setVoiceSupported(ok);

    if (!ok) return;

    const rec = new Rec();
    const langLower = currentVoiceLang.toLowerCase();
    // For Bosnian UI, prefer a broadly supported recognition locale if bs-BA is missing.
    const sttLang = langLower.startsWith("bs") ? "hr-HR" : currentVoiceLang;
    rec.lang = sttLang;
    rec.interimResults = true;
    rec.continuous = false;

    rec.onresult = (ev: any) => {
      // Any new input during the grace period cancels auto-send.
      clearAutoSendGraceTimer();

      let finalText = "";
      let interim = "";
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const r = ev.results[i];
        const t = String(r?.[0]?.transcript ?? "");
        if (r.isFinal) finalText += t;
        else interim += t;
      }

      voiceLastResultAtMsRef.current = Date.now();
      if (finalText.trim()) {
        voiceLastFinalRef.current = finalText.trim();
      }

      const combined = (finalText || interim || "").trim();
      if (combined) {
        lastDraftFromVoiceRef.current = true;
        setDraft(combined);
      }

      // iOS/WebView reliability fallback:
      // If `onend` doesn't fire (or fires late), arm the same grace-based auto-send
      // on a final transcript *without* sending immediately.
      if (
        autoSendOnVoiceFinalEnabled &&
        isIosDevice() &&
        finalText.trim() &&
        autoSendSentForSessionRef.current !== autoSendSessionRef.current
      ) {
        const sessionId = autoSendSessionRef.current;
        const anchorAt = voiceLastResultAtMsRef.current;
        const txt = (voiceLastFinalRef.current || "").trim();
        if (!txt) return;

        clearAutoSendGraceTimer();
        autoSendGraceTimerRef.current = window.setTimeout(() => {
          autoSendGraceTimerRef.current = null;
          const nowMs = Date.now();
          if (
            !shouldFireVoiceAutoSendAfterGrace({
              sessionId,
              currentSessionId: autoSendSessionRef.current,
              sentForSessionId: autoSendSentForSessionRef.current,
              lastResultAtMs: voiceLastResultAtMsRef.current,
              anchorAtMs: anchorAt,
              nowMs,
              graceMs: VOICE_AUTO_SEND_GRACE_MS,
              text: txt,
            })
          ) {
            return;
          }

          autoSendSentForSessionRef.current = sessionId;
          voiceLastFinalRef.current = "";
          void sendChatFromText(txt, { origin: "voice" });
        }, VOICE_AUTO_SEND_GRACE_MS);
      }
    };

    rec.onerror = () => {
      setListening(false);
      clearAutoSendGraceTimer();
    };

    rec.onend = () => {
      setListening(false);

      if (!autoSendOnVoiceFinalEnabled) return;

      const sessionId = autoSendSessionRef.current;
      const endAt = Date.now();
      const txt = (voiceLastFinalRef.current || "").trim();
      if (!txt) return;

      // Guard against double-send for the same voice session.
      if (autoSendSentForSessionRef.current === sessionId) return;

      clearAutoSendGraceTimer();
      autoSendGraceTimerRef.current = window.setTimeout(() => {
        autoSendGraceTimerRef.current = null;
        // Cancel if a new voice session started.
        const nowMs = Date.now();
        if (
          !shouldFireVoiceAutoSendAfterGrace({
            sessionId,
            currentSessionId: autoSendSessionRef.current,
            sentForSessionId: autoSendSentForSessionRef.current,
            lastResultAtMs: voiceLastResultAtMsRef.current,
            anchorAtMs: endAt,
            nowMs,
            graceMs: VOICE_AUTO_SEND_GRACE_MS,
            text: txt,
          })
        ) {
          return;
        }

        autoSendSentForSessionRef.current = sessionId;
        voiceLastFinalRef.current = "";
        void sendChatFromText(txt, { origin: "voice" });
      }, VOICE_AUTO_SEND_GRACE_MS);
    };

    recognitionRef.current = rec;

    return () => {
      try {
        rec.onresult = null;
        rec.onerror = null;
        rec.onend = null;
        rec.stop?.();
      } catch {
        // ignore
      }
      recognitionRef.current = null;
    };
    // NOTE: submit is stable (useCallback) but declared later; we intentionally
    // avoid adding it to deps to keep TypeScript happy and rely on current closure.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [voiceEnabled, autoSendOnVoiceFinalEnabled, currentVoiceLang, clearAutoSendGraceTimer, isIosDevice]);

  const toggleVoice = useCallback(() => {
    if (!voiceEnabled) return;
    const rec = recognitionRef.current;
    if (!rec) return;

    if (listening) {
      try {
        rec.stop();
      } catch {
        // ignore
      }
      setListening(false);
      return;
    }

    try {
      // New voice session: cancel any pending auto-send.
      clearAutoSendGraceTimer();
      voiceLastFinalRef.current = "";
      voiceLastResultAtMsRef.current = 0;
      autoSendSessionRef.current += 1;
      setListening(true);
      rec.start();
    } catch {
      setListening(false);
    }
  }, [voiceEnabled, listening, clearAutoSendGraceTimer]);

  const attachBackendAudioIfPresent = useCallback(
    (messageId: string, resp: NormalizedConsoleResponse) => {
      const vo = extractVoiceOutputFromResponse(resp);
      const audio = createAudioFromVoiceOutputUsingGlobals(vo);
      if (!audio) return;

      const prev = audioUrlByMsgIdRef.current.get(messageId);
      if (prev && prev !== audio.url) safeRevokeObjectUrl(prev);
      audioUrlByMsgIdRef.current.set(messageId, audio.url);

      updateItem(messageId, {
        audioUrl: audio.url,
        audioContentType: audio.contentType,
      } as any);
    },
    [updateItem]
  );

  const deriveVoiceDebugPath = useCallback((resp: NormalizedConsoleResponse) => {
    const ep = (resp as any)?.source_endpoint;
    const s = typeof ep === "string" ? ep : "";
    if (!s) return "chat" as const;
    if (s.startsWith("ws:") || s.startsWith("wss:") || s.includes("/voice/realtime/ws")) return "voice_ws" as const;
    if (s.includes("/voice/exec_text")) return "voice_http" as const;
    return "chat" as const;
  }, []);

  const attachVoiceDebugIfPresent = useCallback(
    (messageId: string, resp: NormalizedConsoleResponse) => {
      const vo = extractVoiceOutputFromResponse(resp);
      const path = deriveVoiceDebugPath(resp);
      const reason = vo && typeof (vo as any).reason === "string" ? String((vo as any).reason) : undefined;
      const backendAudio = Boolean(vo && (vo as any).available === true);
      const hasAudioUrl = audioUrlByMsgIdRef.current.has(messageId);
      const sourceEndpoint = typeof (resp as any)?.source_endpoint === "string" ? String((resp as any).source_endpoint) : undefined;

      updateItem(messageId, {
        voiceDebug: {
          backend_audio: backendAudio,
          audioUrl: hasAudioUrl,
          voice_output_reason: reason,
          path,
          source_endpoint: sourceEndpoint,
        },
      } as any);
    },
    [deriveVoiceDebugPath, updateItem]
  );

  // ------------------------------
  // APPROVAL FLOW HELPERS
  // ------------------------------
  const handleOpenApprovals = useCallback(
    (approvalRequestId?: string) => {
      if (onOpenApprovals) onOpenApprovals(approvalRequestId);
      else window.dispatchEvent(new CustomEvent("ceo:openApprovals", { detail: { approvalRequestId } }));
    },
    [onOpenApprovals]
  );

  /**
   * Step A: Create execution (BLOCKED) from the EXACT proposal object.
   */
  const handleCreateExecutionFromProposal = useCallback(
    async (proposal: ProposedCmd) => {
      if (busy === "submitting" || busy === "streaming") return;

      setBusy("submitting");
      setLastError(null);

      const placeholder = makeSystemProcessingItem("proposal_create_execution");
      appendItem(placeholder);

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        // Ensure metadata includes session_id
        const proposalWithSession = {
          ...proposal,
          metadata: {
            ...(proposal.metadata || {}),
            session_id: sessionId,
            source: "ceo_dashboard",
          },
        };

        const key = getProposalKey(proposal);
        const execUrl = resolveEndpoint(executeRawUrl, "/api/execute/raw");

        const execJson = enterprisePreviewEditorEnabled
          ? await postJson(
              execUrl,
              {
                ...proposalWithSession,
                patches: proposalEnterprisePatches[key] || [],
              },
              controller.signal,
            )
          : await postJson(
              execUrl,
              applyPatchToProposal(proposalWithSession, proposalPatches[key]),
              controller.signal,
            );

        const approvalId: string | null =
          typeof execJson?.approval_id === "string" && execJson.approval_id ? execJson.approval_id : null;

        const executionId: string | null =
          typeof execJson?.execution_id === "string" && execJson.execution_id ? execJson.execution_id : null;

        const msg =
          approvalId?.trim()
            ? `Execution created (BLOCKED). approval_id: ${approvalId}`
            : _pickText(execJson) || "Execution created.";

        updateItem(placeholder.id, { content: msg, status: "final" });

        if (approvalId) {
          appendItem({
            id: uid(),
            kind: "governance",
            createdAt: now(),
            state: "BLOCKED",
            title: "Pending approval",
            summary: executionId ? `execution_id: ${executionId}` : "Execution created and waiting for approval.",
            reasons: [],
            approvalRequestId: approvalId,
            requestId: (execJson as any)?.requestId,
          } as GovernanceEventItem);

          handleOpenApprovals(approvalId);
        }

        abortRef.current = null;
        setBusy("idle");
        setLastError(null);
      } catch (e) {
        abortRef.current = null;
        const msg = e instanceof Error ? e.message : String(e);
        updateItem(placeholder.id, { status: "error", content: "" });
        setBusy(isAbortError(e) ? "idle" : "error");
        setLastError(isAbortError(e) ? null : msg);
      }
    },
    [
      appendItem,
      applyPatchToProposal,
      busy,
      executeRawUrl,
      getProposalKey,
      handleOpenApprovals,
      postJson,
      proposalEnterprisePatches,
      proposalPatches,
      resolveEndpoint,
      sessionId,
      updateItem,
    ]
  );

  /**
   * Step B: Approve using approval_id.
   */
  const handleApprove = useCallback(
    async (approvalId: string) => {
      const appUrl = resolveEndpoint(effectiveApproveUrl, "/api/ai-ops/approval/approve");
      if (busy === "submitting" || busy === "streaming") return;

      setBusy("submitting");
      setLastError(null);

      const placeholder = makeSystemProcessingItem(approvalId);
      appendItem(placeholder);

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        // Approve can return 422 with a structured JSON body; do not rely on postJson (it throws on non-2xx).
        const res = await fetch(appUrl, {
          method: "POST",
          headers: mergedHeaders,
          body: JSON.stringify({ approval_id: approvalId }),
          signal: controller.signal,
        });
        const txt = await res.text();
        let approveJson: any = {};
        try {
          approveJson = txt ? JSON.parse(txt) : {};
        } catch {
          approveJson = { ok: res.ok, message: txt || "" };
        }

        const opErrors: any[] = Array.isArray(approveJson?.operation_errors)
          ? (approveJson.operation_errors as any[])
          : [];

        const msg = opErrors.length
          ? (() => {
              const lines: string[] = [];
              lines.push("Blocked because:");
              for (const it of opErrors.slice(0, 20)) {
                if (!it || typeof it !== "object") continue;
                const oid = typeof (it as any).op_id === "string" ? (it as any).op_id : "";
                const field = typeof (it as any).field === "string" ? (it as any).field : "";
                const code = typeof (it as any).code === "string" ? (it as any).code : "error";
                const m = typeof (it as any).message === "string" ? (it as any).message : "Operation failed";
                const head = oid ? oid : "(op)";
                const mid = field ? ` · ${field}` : "";
                lines.push(`- ${head}${mid} · ${code}: ${m}`);
              }
              return lines.join("\n");
            })()
          : _pickText(approveJson) ||
            (approveJson?.execution_state ? `Execution: ${approveJson.execution_state}` : res.ok ? "Approved." : "Approval failed.");

        updateItem(placeholder.id, { content: msg, status: "final" });

        const notionLinks = extractNotionLinksFromApproveResponse(approveJson);
        const refMap = extractRefMapFromApproveResponse(approveJson);

        if (notionLinks.length > 0 || Object.keys(refMap).length > 0) {
          appendItem({
            id: uid(),
            kind: "governance",
            createdAt: now(),
            state: (approveJson?.execution_state as any) || "EXECUTED",
            title: "Execution result",
            summary: msg,
            reasons: [],
            approvalRequestId: approvalId,
            requestId: approvalId,
            notionLinks,
            refMap,
          } as GovernanceEventItem);
        }

        abortRef.current = null;
        setBusy("idle");
        setLastError(null);
      } catch (e) {
        abortRef.current = null;
        const msg = e instanceof Error ? e.message : String(e);
        updateItem(placeholder.id, { status: "error", content: "" });
        setBusy(isAbortError(e) ? "idle" : "error");
        setLastError(isAbortError(e) ? null : msg);
      }
    },
    [appendItem, effectiveApproveUrl, busy, mergedHeaders, resolveEndpoint, updateItem]
  );

  /**
   * OPTIONAL: Reject/Disapprove approval_id (if backend supports).
   */
  const handleReject = useCallback(
    async (approvalId: string) => {
      const rejUrl = resolveEndpoint(effectiveRejectUrl, "/api/ai-ops/approval/reject");
      if (busy === "submitting" || busy === "streaming") return;

      setBusy("submitting");
      setLastError(null);

      const placeholder = makeSystemProcessingItem(approvalId);
      appendItem(placeholder);

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        const rejectJson = await postJson(rejUrl, { approval_id: approvalId }, controller.signal);
        const msg = _pickText(rejectJson) || "Rejected.";

        updateItem(placeholder.id, { content: msg, status: "final" });
        abortRef.current = null;
        setBusy("idle");
        setLastError(null);
      } catch (e) {
        abortRef.current = null;
        const msg = e instanceof Error ? e.message : String(e);
        updateItem(placeholder.id, { status: "error", content: "" });
        setBusy(isAbortError(e) ? "idle" : "error");
        setLastError(isAbortError(e) ? null : msg);
      }
    },
    [appendItem, effectiveRejectUrl, busy, postJson, resolveEndpoint, updateItem]
  );

  /**
   * Single click "Approve" on a proposal:
   * - create execution (BLOCKED)
   * - then approve via approval_id
   */
  const handleApproveProposal = useCallback(
    async (proposal: ProposedCmd) => {
      if (busy === "submitting" || busy === "streaming") return;

      setBusy("submitting");
      setLastError(null);

      const placeholder = makeSystemProcessingItem("approve_proposal");
      appendItem(placeholder);

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        // Ensure metadata includes session_id
        const proposalWithSession = {
          ...proposal,
          metadata: {
            ...(proposal.metadata || {}),
            session_id: sessionId,
            source: "ceo_dashboard",
          },
        };

        const key = getProposalKey(proposalWithSession as any);

        const execPayload = enterprisePreviewEditorEnabled
          ? {
              ...(proposalWithSession as any),
              patches: proposalEnterprisePatches[key] || [],
            }
          : applyPatchToProposal(proposalWithSession as any, proposalPatches[key]);

        const execUrl = resolveEndpoint(executeRawUrl, "/api/execute/raw");
        const execJson = await postJson(execUrl, execPayload, controller.signal);

        const approvalId: string | null =
          typeof execJson?.approval_id === "string" && execJson.approval_id ? execJson.approval_id : null;

        if (!approvalId) {
          updateItem(placeholder.id, {
            content: _pickText(execJson) || "Execution created, but approval_id missing.",
            status: "final",
          });
          abortRef.current = null;
          setBusy("idle");
          return;
        }

        const appUrl = resolveEndpoint(effectiveApproveUrl, "/api/ai-ops/approval/approve");
        const approveJson = await postJson(appUrl, { approval_id: approvalId }, controller.signal);

        const msg =
          _pickText(approveJson) ||
          (approveJson?.execution_state
            ? `Execution: ${approveJson.execution_state}`
            : `Approved. approval_id: ${approvalId}`);

        updateItem(placeholder.id, { content: msg, status: "final" });

        const notionLinks = extractNotionLinksFromApproveResponse(approveJson);
        const refMap = extractRefMapFromApproveResponse(approveJson);

        if (notionLinks.length > 0 || Object.keys(refMap).length > 0) {
          appendItem({
            id: uid(),
            kind: "governance",
            createdAt: now(),
            state: (approveJson?.execution_state as any) || "EXECUTED",
            title: "Execution result",
            summary: msg,
            reasons: [],
            approvalRequestId: approvalId,
            requestId: approvalId,
            notionLinks,
            refMap,
          } as GovernanceEventItem);
        }

        abortRef.current = null;
        setBusy("idle");
        setLastError(null);
      } catch (e) {
        abortRef.current = null;
        const msg = e instanceof Error ? e.message : String(e);
        updateItem(placeholder.id, { status: "error", content: "" });
        setBusy(isAbortError(e) ? "idle" : "error");
        setLastError(isAbortError(e) ? null : msg);
      }
    },
    [
      appendItem,
      applyPatchToProposal,
      busy,
      effectiveApproveUrl,
      executeRawUrl,
      getProposalKey,
      postJson,
      proposalEnterprisePatches,
      proposalPatches,
      resolveEndpoint,
      sessionId,
      updateItem,
    ]
  );

  // ------------------------------
  // CHAT RESPONSE -> UI
  // ------------------------------
  const flushResponseToUi = useCallback(
    async (placeholderId: string, resp: NormalizedConsoleResponse) => {
      if ((resp as any).stream) {
        setBusy("streaming");
        updateItem(placeholderId, { content: "", status: "streaming" });

        // Debug visibility: record which transport we are using as early as possible.
        attachVoiceDebugIfPresent(placeholderId, resp);

        let acc = "";
        try {
          for await (const chunk of (resp as any).stream) {
            acc += chunk;
            updateItem(placeholderId, { content: acc, status: "streaming" });
            if (isPinnedToBottom) scrollToBottom(false);
          }

          // Best-effort: recover canonical final response payload for parity.
          const finalPromise = (resp as any)?.stream?.finalResponse;
          let finalRaw: any = null;
          if (finalPromise && typeof finalPromise.then === "function") {
            finalRaw = await finalPromise;
          }

          const respAfter: any =
            finalRaw && typeof finalRaw === "object" ? { ...(resp as any), raw: finalRaw } : (resp as any);

          updateItem(placeholderId, { content: acc.trim(), status: "final" });

          attachBackendAudioIfPresent(placeholderId, respAfter);
          attachVoiceDebugIfPresent(placeholderId, respAfter);

          // Unified voice output: prefer backend audio. Browser speechSynthesis is fallback-only.
          if (ttsEnabled && (autoSpeakEnabled || autoSendOnVoiceFinalEnabled) && acc.trim()) {
            const url = audioUrlByMsgIdRef.current.get(placeholderId);
            if (url) {
              void tryAutoplayBackendAudioUrl(url);
            } else if (ttsSupported) {
              speak(acc.trim());
            }
          }

          // Governance/proposals parity: evaluate proposals from assistant.final payload.
          const proposalsRaw = _extractProposedCommands(respAfter);
          const proposals = proposalsRaw.filter(isActionableProposal);
          const actionableCount = proposals.length;

          const gov = toGovernanceCard(respAfter as any);
          if (gov && shouldShowBackendGovernanceCard(gov, actionableCount)) appendItem(gov);

          if (actionableCount > 0) {
            appendItem({
              id: uid(),
              kind: "governance",
              createdAt: now(),
              state: "BLOCKED",
              title: "Approval required",
              summary: "Review the proposed action and either approve or dismiss it.",
              reasons: undefined,
              approvalRequestId: undefined,
              requestId: (respAfter as any)?.requestId,
              proposedCommands: proposals,
            } as any);
          }
          
          setBusy("idle");
          setLastError(null);
        } catch (e) {
          // Let caller decide whether to fallback to non-streaming.
          throw e;
        }
        return;
      }

      // ✅ FIX (evidence-based): NormalizedConsoleResponse uses `systemText`, so prefer it explicitly.
      const sysText =
        _pickText(resp as any) ||
        (typeof (resp as any)?.systemText === "string" ? (resp as any).systemText.trim() : "") ||
        _pickText((resp as any)?.result) ||
        _pickText((resp as any)?.raw) ||
        _pickText((resp as any)?.data) ||
        "";

      updateItem(placeholderId, { content: sysText, status: "final" });

      attachBackendAudioIfPresent(placeholderId, resp);
      attachVoiceDebugIfPresent(placeholderId, resp);

      // Unified voice output: prefer backend audio. Browser speechSynthesis is fallback-only.
      if (ttsEnabled && (autoSpeakEnabled || autoSendOnVoiceFinalEnabled) && sysText) {
        const url = audioUrlByMsgIdRef.current.get(placeholderId);
        if (url) {
          void tryAutoplayBackendAudioUrl(url);
        } else if (ttsSupported) {
          speak(sysText);
        }
      }

      const proposalsRaw = _extractProposedCommands(resp as any);
      const proposals = proposalsRaw.filter(isActionableProposal);
      const actionableCount = proposals.length;

      const gov = toGovernanceCard(resp);
      if (gov && shouldShowBackendGovernanceCard(gov, actionableCount)) appendItem(gov);

      // CANON: any actionable proposals => show governance BLOCKED entrypoint
      if (actionableCount > 0) {
        appendItem({
          id: uid(),
          kind: "governance",
          createdAt: now(),
          state: "BLOCKED",
          title: "Approval required",
          summary: "Review the proposed action and either approve or dismiss it.",
          reasons: undefined,
          approvalRequestId: undefined,
          requestId: (resp as any)?.requestId,
          proposedCommands: proposals,
        } as any);
      }

      setBusy("idle");
      setLastError(null);
    },
    [
      appendItem,
      updateItem,
      isPinnedToBottom,
      scrollToBottom,
      ttsEnabled,
      autoSpeakEnabled,
      autoSendOnVoiceFinalEnabled,
      speak,
      ttsSupported,
      attachBackendAudioIfPresent,
      attachVoiceDebugIfPresent,
      tryAutoplayBackendAudioUrl,
    ]
  );

  // ------------------------------
  // NOTION READ (page_by_title)
  // ------------------------------
  const [notionQuery, setNotionQuery] = useState<string>("");
  const [notionLoading, setNotionLoading] = useState<boolean>(false);
  const [notionLastError, setNotionLastError] = useState<string | null>(null);

  const runNotionSearch = useCallback(async () => {
    const q = notionQuery.trim();
    if (!q) {
      setNotionLastError("Unesi naziv dokumenta (title) za pretragu.");
      return;
    }
    if (busy === "submitting" || busy === "streaming") return;

    setNotionLastError(null);
    setNotionLoading(true);

    const placeholder = makeSystemProcessingItem("notion_read");
    appendItem(placeholder);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = await (api as any).notionReadPageByTitle?.(q, controller.signal);

      if (!res || res.ok !== true) {
        const err = typeof res?.error === "string" && res.error.trim() ? res.error.trim() : "Document not found.";
        updateItem(placeholder.id, {
          content: `Document not found for query: "${q}"\n\n${err}`,
          status: "final",
        });
        abortRef.current = null;
        setNotionLoading(false);
        return;
      }

      const title = typeof res.title === "string" && res.title.trim() ? res.title.trim() : q;
      const notionUrl = typeof res.notion_url === "string" && res.notion_url.trim() ? res.notion_url.trim() : "";

      const contentMd = typeof res.content_markdown === "string" && res.content_markdown ? res.content_markdown : "";

      const docText =
        `${title}\n` +
        `${"=".repeat(Math.min(80, Math.max(10, title.length)))}\n\n` +
        (notionUrl ? `Open in Notion: ${notionUrl}\n\n` : "") +
        truncateText(contentMd, 20000);

      updateItem(placeholder.id, { content: docText, status: "final" });

      abortRef.current = null;
      setNotionLoading(false);
      setLastError(null);
    } catch (e) {
      abortRef.current = null;
      const msg = e instanceof Error ? e.message : String(e);
      updateItem(placeholder.id, { status: "error", content: "" });
      setNotionLoading(false);
      setNotionLastError(isAbortError(e) ? null : msg);
      setLastError(isAbortError(e) ? null : msg);
    }
  }, [api, appendItem, busy, notionQuery, updateItem]);

  // ------------------------------
  // SUBMIT CHAT
  // ------------------------------
  const submit = useCallback(async () => {
    await sendChatFromText(draft);
  }, [draft, sendChatFromText]);

  const onKeyDown = useCallback(
    (ev: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (ev.key !== "Enter") return;
      if (ev.shiftKey) return;
      ev.preventDefault();
      void submit();
    },
    [submit]
  );

  const canSend = busy === "idle" && draft.trim().length > 0;
  const showTyping = busy === "submitting" || busy === "streaming";
  const jumpToLatest = useCallback(() => scrollToBottom(true), [scrollToBottom]);

  const retryLast = useCallback(() => {
    setBusy("idle");
    setLastError(null);
    setNotionLastError(null);
  }, []);

  return (
    <section className={`ceoChatbox ${className ?? ""}`.trim()}>
      <CommandPreviewModal
        open={previewOpen}
        title={previewTitle}
        loading={previewLoading}
        error={previewError}
        data={previewData}
        enterprisePreviewEditorEnabled={enterprisePreviewEditorEnabled}
        enterprisePatches={
          previewProposalKey ? proposalEnterprisePatches[previewProposalKey] || [] : []
        }
        onEnterprisePatchesChange={(patches) => {
          if (!previewProposalKey) return;
          const list = Array.isArray(patches)
            ? (patches as EnterpriseOpPatch[])
            : [];
          setProposalEnterprisePatches((prev) => ({
            ...prev,
            [previewProposalKey]: list,
          }));

          if (enterprisePreviewEditorEnabled) {
            const sig = stableStringify(list);
            setEnterprisePreviewGateByKey((prev) => ({
              ...prev,
              [previewProposalKey]: {
                patchesSig: sig,
                canApprove: false,
                errors: 1,
                dirty: true,
              },
            }));
          }
        }}
        onApplyPatch={(patch) => {
          if (!previewProposalKey) return;
          if (enterprisePreviewEditorEnabled) {
            const list = Array.isArray(patch)
              ? (patch as EnterpriseOpPatch[])
              : [];
            setProposalEnterprisePatches((prev) => ({
              ...prev,
              [previewProposalKey]: list,
            }));

            if (previewProposal)
              void handlePreviewProposal(previewProposal, previewProposalLabel, list);
            return;
          }

          const merged = {
            ...(proposalPatches[previewProposalKey] || {}),
            ...(patch || {}),
          };
          setProposalPatches((prev) => ({ ...prev, [previewProposalKey]: merged }));
          if (previewProposal)
            void handlePreviewProposal(
              applyPatchToProposal(previewProposal, merged),
              previewProposalLabel,
            );
        }}
        onClose={() => {
          previewAbortRef.current?.abort();
          previewAbortRef.current = null;
          setPreviewOpen(false);
        }}
      />

      <Header
        title={ui.headerTitle}
        subtitle={ui.headerSubtitle}
        onVoiceToggle={voiceEnabled && voiceSupported ? toggleVoice : undefined}
        voiceListening={listening}
        voiceSupported={voiceEnabled && voiceSupported}
        onStopCurrent={stopCurrent}
        showStop={busy === "submitting" || busy === "streaming" || notionLoading}
        onJumpToLatest={jumpToLatest}
        showJump={!isPinnedToBottom}
        disabled={busy === "submitting" || busy === "streaming"}
        language={currentVoiceLang}
        onLanguageChange={(lang) => {
          setCurrentVoiceLang(lang);
          try {
            if (typeof window !== 'undefined') {
              localStorage.setItem('ceo_voice_lang', lang);
            }
          } catch {}
        }}
        ttsVoices={ttsVoiceOptions}
        selectedTtsVoiceId={selectedVoiceName || ''}
        onTtsVoiceChange={(id) => {
          selectVoiceByName(id || null);
          try {
            if (typeof window !== 'undefined') {
              localStorage.setItem('ceo_voice_name', id || '');
            }
          } catch {}
        }}
        enableVoice={voiceEnabled}
        onEnableVoiceChange={(val) => {
          setVoiceEnabled(val);
          try {
            if (typeof window !== 'undefined') {
              localStorage.setItem('ceo_voice_enabled', val ? 'true' : 'false');
            }
          } catch {}
        }}
        enableTTS={ttsEnabled}
        onEnableTTSChange={(val) => {
          setTtsEnabled(val);
          try {
            if (typeof window !== 'undefined') {
              localStorage.setItem('ceo_tts_enabled', val ? 'true' : 'false');
            }
          } catch {}
        }}
        autoSpeak={autoSpeakEnabled}
        onAutoSpeakChange={(val) => {
          setAutoSpeakEnabled(val);
          try {
            if (typeof window !== 'undefined') {
              localStorage.setItem('ceo_auto_speak', val ? 'true' : 'false');
            }
          } catch {}
        }}
        autoSendOnVoiceFinal={autoSendOnVoiceFinalEnabled}
        onAutoSendOnVoiceFinalChange={(val) => {
          setAutoSendOnVoiceFinalEnabled(val);
          try {
            if (typeof window !== 'undefined') {
              localStorage.setItem('ceo_auto_send_voice', val ? 'true' : 'false');
            }
          } catch {}
        }}
        speechRate={speechRate}
        onSpeechRateChange={(val) => {
          const clamped = Math.min(1.8, Math.max(0.6, val));
          setSpeechRate(clamped);
          try {
            if (typeof window !== 'undefined') {
              localStorage.setItem('ceo_speech_rate', String(clamped));
            }
          } catch {}
        }}
        speechPitch={speechPitch}
        onSpeechPitchChange={(val) => {
          const clamped = Math.min(1.6, Math.max(0.6, val));
          setSpeechPitch(clamped);
          try {
            if (typeof window !== 'undefined') {
              localStorage.setItem('ceo_speech_pitch', String(clamped));
            }
          } catch {}
        }}
        outputLanguage={outputLanguage}
        onOutputLanguageChange={(val) => {
          const norm = val === 'en' || val === 'bs' || val === 'hr' || val === 'sr' || val === 'de' ? val : 'bs';
          setOutputLanguage(norm);
          try {
            if (typeof window !== 'undefined') {
              localStorage.setItem('ceo_output_lang', norm);
            }
          } catch {}
        }}

        backendVoiceAgents={backendVoiceAgents}
        backendVoicePresets={backendVoicePresets}
        backendVoiceTargetAgentId={voiceProfileTargetAgentId}
        onBackendVoiceTargetAgentIdChange={(id) => {
          setVoiceProfileTargetAgentId(id);
          try {
            if (typeof window !== 'undefined') {
              localStorage.setItem('ceo_backend_voice_target_agent', id);
            }
          } catch {}
        }}
        backendVoiceProfile={backendVoiceProfiles[voiceProfileTargetAgentId] || {}}
        onBackendVoiceProfileChange={(patch) => {
          setBackendVoiceProfiles((prev) => {
            const next = { ...(prev || {}) } as Record<string, BackendVoiceProfile>;
            const cur = next[voiceProfileTargetAgentId] || {};
            next[voiceProfileTargetAgentId] = { ...cur, ...(patch || {}) };
            try {
              if (typeof window !== 'undefined') {
                localStorage.setItem('ceo_backend_voice_profiles_v1', JSON.stringify(next));
              }
            } catch {}
            return next;
          });
        }}
      />

      <div className="ceoViewport" ref={viewportRef}>
        <div className="ceoList">
          {items.map((it) => {
            if (it.kind === "message") {
              const rowSide = it.role === "ceo" ? "right" : "left";
              const dotCls =
                it.status === "error"
                  ? "ceoStatusDot err"
                  : it.status === "final"
                    ? "ceoStatusDot ok"
                    : "ceoStatusDot";

              return (
                <div className={`ceoRow ${rowSide}`} key={it.id}>
                  <div className={`ceoBubble ${it.role}`}>
                    {it.role === "system" && it.status === "streaming" && !it.content ? (
                      <span className="ceoTyping">
                        <span>{ui.processingLabel}</span>
                        <span className="ceoDots" aria-hidden="true">
                          <span className="ceoDot" />
                          <span className="ceoDot" />
                          <span className="ceoDot" />
                        </span>
                      </span>
                    ) : (
                      typeof it.content === "string" ? renderTextWithNotionLink(it.content) : it.content
                    )}

                    {it.role === "system" && it.status === "final" && it.audioUrl ? (
                      <div className="ceoAudioWrap">
                        <audio
                          className="ceoAudio"
                          controls
                          src={it.audioUrl}
                          preload="none"
                        />
                      </div>
                    ) : null}
                    <div className="ceoMeta">
                      <span className={dotCls} />
                      <span>{formatTime(it.createdAt)}</span>
                      {it.role === "system" && (it as any).voiceDebug ? (
                        <span className="ceoMetaDebug">
                          backend_audio={String(Boolean((it as any).voiceDebug.backend_audio))} audioUrl={String(Boolean((it as any).voiceDebug.audioUrl))} reason={String(((it as any).voiceDebug.voice_output_reason ?? "") as any)} path={String(((it as any).voiceDebug.path ?? "") as any)}
                        </span>
                      ) : null}
                      {ttsEnabled &&
                        ttsSupported &&
                        it.role === "system" &&
                        !it.audioUrl &&
                        it.content &&
                        it.status === "final" && (
                        <button
                          className="ceoMetaButton"
                          onClick={() => speak(String(it.content))}
                          disabled={speaking}
                          title="Speak this message"
                        >
                          🔊
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              );
            }

            const badgeClass =
              it.state === "BLOCKED" ? "blocked" : it.state === "APPROVED" ? "approved" : "executed";

            const badgeText =
              it.state === "BLOCKED" ? ui.blockedLabel : it.state === "APPROVED" ? ui.approvedLabel : ui.executedLabel;

            const proposedCommands: ProposedCmd[] = ((it as any)?.proposedCommands as ProposedCmd[]) ?? [];
            const hasApprovalId = Boolean((it as any)?.approvalRequestId);
            const notionLinks: NotionLinkItem[] = ((it as any)?.notionLinks as NotionLinkItem[]) ?? [];
            const refMap: Record<string, string> = ((it as any)?.refMap as Record<string, string>) ?? {};

            return (
              <div className="ceoRow left" key={it.id}>
                <div className="govCard">
                  <div className="govTop">
                    <div className="govTitle">{it.title ?? ""}</div>
                    <div className={`govBadge ${badgeClass}`}>{badgeText}</div>
                  </div>

                  <div className="govBody">
                    {it.summary ? <div className="govSummary">{it.summary}</div> : null}

                    {notionLinks.length > 0 ? <NotionLinksPanel items={notionLinks} /> : null}
                    {Object.keys(refMap).length > 0 ? <RefMapPanel refMap={refMap} /> : null}

                    {proposedCommands.length > 0 ? (
                      <div style={{ marginTop: 10 }}>
                        <ul className="govReasons" style={{ marginTop: 0 }}>
                          {proposedCommands.map((p, idx) => {
                            const label = proposalLabel(p, idx);

                            const proposalKey = getProposalKey(p, label);
                            const enterprisePatchesForProposal = enterprisePreviewEditorEnabled
                              ? (proposalEnterprisePatches[proposalKey] || [])
                              : [];
                            const enterpriseSig = stableStringify(enterprisePatchesForProposal);
                            const gate = enterprisePreviewGateByKey[proposalKey];
                            const enterpriseNeedsPreview =
                              enterprisePreviewEditorEnabled &&
                              enterprisePatchesForProposal.length > 0 &&
                              (!gate || gate.dirty || gate.patchesSig !== enterpriseSig);
                            const enterpriseBlockedByValidation =
                              enterprisePreviewEditorEnabled &&
                              enterprisePatchesForProposal.length > 0 &&
                              Boolean(gate && (gate.canApprove === false || (gate.errors || 0) > 0));

                            return (
                              <li key={`${it.id}_p_${idx}`}>
                                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                                  <span style={{ fontWeight: 600 }}>{label}</span>

                                  <div style={{ display: "flex", gap: 8, marginLeft: "auto", flexWrap: "wrap" }}>
                                    <button
                                      className="govButton"
                                      onClick={() => void handlePreviewProposal(p, label)}
                                      disabled={
                                        busy === "submitting" ||
                                        busy === "streaming" ||
                                        notionLoading ||
                                        previewLoading
                                      }
                                      title="Preview the exact payload (no approvals)"
                                    >
                                      Preview
                                    </button>

                                    <button
                                      className="govButton"
                                      onClick={() => void handleApproveProposal(p)}
                                      disabled={
                                        busy === "submitting" ||
                                        busy === "streaming" ||
                                        notionLoading ||
                                        enterpriseNeedsPreview ||
                                        enterpriseBlockedByValidation
                                      }
                                      title={
                                        enterpriseNeedsPreview
                                          ? "Update Preview to validate patches before approving"
                                          : enterpriseBlockedByValidation
                                            ? "Blocked by validation errors in Preview"
                                            : "Create execution and approve"
                                      }
                                    >
                                      Approve
                                    </button>

                                    <button
                                      className="govButton"
                                      onClick={() => removeItem(it.id)}
                                      disabled={busy === "submitting" || busy === "streaming" || notionLoading}
                                      title="Dismiss (no backend action)"
                                    >
                                      Dismiss
                                    </button>

                                    <button
                                      className="govButton"
                                      onClick={() => void handleCreateExecutionFromProposal(p)}
                                      disabled={busy === "submitting" || busy === "streaming" || notionLoading}
                                      title="Create execution only (BLOCKED)"
                                    >
                                      Create (Blocked)
                                    </button>
                                  </div>
                                </div>
                              </li>
                            );
                          })}
                        </ul>
                      </div>
                    ) : null}

                    {hasApprovalId ? (
                      <div className="govActions">
                        <button className="govButton" onClick={() => handleOpenApprovals((it as any).approvalRequestId)}>
                          {ui.openApprovalsLabel}
                        </button>

                        {it.state === "BLOCKED" ? (
                          <>
                            <button
                              className="govButton"
                              onClick={() => void handleApprove((it as any).approvalRequestId)}
                              disabled={busy === "submitting" || busy === "streaming" || notionLoading}
                            >
                              {ui.approveLabel}
                            </button>

                            <button
                              className="govButton"
                              onClick={() => void handleReject((it as any).approvalRequestId)}
                              disabled={busy === "submitting" || busy === "streaming" || notionLoading}
                              title="Requires backend support for /approval/reject"
                            >
                              Disapprove
                            </button>
                          </>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                </div>
              </div>
            );
          })}

          {lastError || notionLastError ? (
            <div className="ceoRow left">
              <div className="govCard">
                <div className="govTop">
                  <div className="govTitle">{""}</div>
                  <div className="govBadge blocked">{ui.blockedLabel}</div>
                </div>
                <div className="govBody">
                  <div className="govSummary">{notionLastError ? `Notion read: ${notionLastError}` : lastError}</div>
                  <div className="govActions">
                    <button className="govButton" onClick={retryLast}>
                      {ui.retryLabel}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          ) : null}
        </div>
      </div>

      <footer className="ceoComposer">
        {/* NOTION OPS STATUS & ACTIVATION */}
        <div className="ceoFooterRow ceoFooterRow-top">
          <div style={{ display: "flex", alignItems: "center", gap: 8, flex: 1 }}>
            <span style={{ fontWeight: 600, opacity: 0.9 }}>Notion Ops:</span>
            <span
              style={{
                padding: "4px 10px",
                borderRadius: 12,
                fontSize: "0.85em",
                fontWeight: 600,
                background: notionOpsArmed ? "rgba(34, 197, 94, 0.2)" : "rgba(239, 68, 68, 0.2)",
                color: notionOpsArmed ? "#22c55e" : "#ef4444",
                border: `1px solid ${notionOpsArmed ? "rgba(34, 197, 94, 0.3)" : "rgba(239, 68, 68, 0.3)"}`,
              }}
            >
              {notionOpsArmed ? "✓ ARMED" : "✗ NOT ARMED"}
            </span>
            {!notionOpsArmed && (
              <span style={{ fontSize: "0.85em", opacity: 0.7 }}>
                (Write operations blocked)
              </span>
            )}
          </div>
          
          <button
            className="ceoHeaderButton"
            onClick={async () => {
              if (busy === "submitting" || busy === "streaming") return;
              
              try {
                setBusy("submitting");
                setLastError(null);
                
                const newArmedState = !notionOpsArmed;
                const toggleUrl = resolveEndpoint(undefined, "/api/notion-ops/toggle");
                
                const res = await fetch(toggleUrl, {
                  method: "POST",
                  headers: mergedHeaders,
                  body: JSON.stringify({
                    session_id: sessionId,
                    armed: newArmedState,
                  }),
                });
                
                if (!res.ok) {
                  const errorText = await res.text().catch(() => "");
                  throw new Error(`Toggle failed (${res.status}): ${errorText || res.statusText}`);
                }
                
                const result = await res.json().catch(() => ({}));
                
                // Update local state
                setNotionOpsArmed(result.armed ?? newArmedState);
                
                // Store in sessionStorage
                if (typeof sessionStorage !== 'undefined') {
                  sessionStorage.setItem('notion_ops_armed', result.armed ? 'true' : 'false');
                }
                
                // Add confirmation message to chat
                appendItem({
                  id: uid(),
                  kind: "message",
                  role: "system",
                  content: result.armed ? "✓ NOTION OPS: ARMED" : "✓ NOTION OPS: DISARMED",
                  status: "final",
                  createdAt: now(),
                });
                
                setBusy("idle");
              } catch (e) {
                const msg = e instanceof Error ? e.message : String(e);
                setLastError(msg);
                setBusy("error");
                
                appendItem({
                  id: uid(),
                  kind: "message",
                  role: "system",
                  content: `Failed to toggle Notion Ops: ${msg}`,
                  status: "error",
                  createdAt: now(),
                });
              }
            }}
            disabled={busy === "submitting" || busy === "streaming"}
            title={notionOpsArmed ? "Deactivate Notion Ops" : "Activate Notion Ops"}
            style={{
              background: notionOpsArmed ? "rgba(239, 68, 68, 0.15)" : "rgba(34, 197, 94, 0.15)",
              border: `1px solid ${notionOpsArmed ? "rgba(239, 68, 68, 0.3)" : "rgba(34, 197, 94, 0.3)"}`,
            }}
          >
            {notionOpsArmed ? "🔒 Deactivate" : "🔓 Activate"}
          </button>
        </div>

        {/* NOTION READ PANEL */}
        <div className="ceoFooterRow ceoFooterRow-search">
          <div style={{ fontWeight: 600, opacity: 0.9 }}>{(ui as any).searchNotionLabel ?? "Search Notion"}</div>

          <input
            value={notionQuery}
            onChange={(e) => setNotionQuery(e.target.value)}
            placeholder={(ui as any).searchQueryPlaceholder ?? 'Document title (e.g. "Outreach SOP")…'}
            disabled={notionLoading || busy === "submitting" || busy === "streaming"}
            className="ceoFooterInput"
          />

          <button
            className="ceoHeaderButton"
            onClick={() => void runNotionSearch()}
            disabled={notionLoading || busy === "submitting" || busy === "streaming" || !notionQuery.trim()}
            title="Read Notion page by title (backend)"
          >
            {notionLoading ? ((ui as any).searchingLabel ?? "Searching…") : ((ui as any).runSearchLabel ?? "Search")}
          </button>
        </div>

        {/* CHAT COMPOSER */}
        <div className="ceoComposerInner">
          <textarea
            className="ceoTextarea"
            ref={composerRef}
            value={draft}
            placeholder={ui.inputPlaceholder}
            onChange={(e) => {
              lastDraftFromVoiceRef.current = false;
              setDraft(e.target.value);
            }}
            onKeyDown={onKeyDown}
            disabled={busy === "submitting" || busy === "streaming"}
            rows={1}
          />

          {voiceEnabled && voiceSupported ? (
            <button
              className="ceoSendBtn"
              onClick={toggleVoice}
              disabled={busy === "submitting" || busy === "streaming"}
              title={listening ? "Stop voice input" : "Start voice input"}
              style={{ width: 120 }}
            >
              {listening ? "Listening…" : "Voice"}
            </button>
          ) : null}

          <button className="ceoSendBtn" onClick={() => void submit()} disabled={!canSend}>
            {ui.sendLabel}
          </button>
        </div>

        <div className="ceoHintRow">
          <span>{""}</span>
          <span>{""}</span>
        </div>

        {showTyping ? (
          <span style={{ display: "none" }} aria-live="polite">
            {ui.processingLabel}
          </span>
        ) : null}
      </footer>
    </section>
  );
};

declare global {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace JSX {
    // eslint-disable-next-line @typescript-eslint/no-empty-interface
    interface IntrinsicElements {
      [elemName: string]: any;
    }
  }
}

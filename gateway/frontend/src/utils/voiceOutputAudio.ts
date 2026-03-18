// gateway/frontend/src/utils/voiceOutputAudio.ts

export type VoiceOutput = {
  available?: boolean;
  content_type?: string;
  audio_base64?: string;
  reason?: string;
  [k: string]: any;
};

export type VoiceOutputAudio = {
  url: string;
  contentType: string;
};

type CreateAudioDeps = {
  atob: (value: string) => string;
  Blob: typeof Blob;
  createObjectURL: (blob: Blob) => string;
};

const DEFAULT_MAX_BASE64_CHARS = 2_000_000;

export function extractVoiceOutputFromResponse(resp: any): VoiceOutput | null {
  if (!resp || typeof resp !== "object") return null;
  const direct = (resp as any).voice_output;
  if (direct && typeof direct === "object") return direct as VoiceOutput;
  const raw = (resp as any).raw;
  const nested = raw && typeof raw === "object" ? (raw as any).voice_output : null;
  return nested && typeof nested === "object" ? (nested as VoiceOutput) : null;
}

export function isPlayableVoiceOutput(vo: VoiceOutput | null | undefined): vo is Required<Pick<VoiceOutput, "content_type" | "audio_base64">> & VoiceOutput {
  if (!vo || typeof vo !== "object") return false;
  if ((vo as any).available !== true) return false;
  return typeof (vo as any).content_type === "string" && typeof (vo as any).audio_base64 === "string";
}

export function createAudioFromVoiceOutput(
  vo: VoiceOutput | null | undefined,
  deps: CreateAudioDeps,
  opts?: { maxBase64Chars?: number }
): VoiceOutputAudio | null {
  if (!isPlayableVoiceOutput(vo)) return null;

  const maxChars = opts?.maxBase64Chars ?? DEFAULT_MAX_BASE64_CHARS;
  if (maxChars > 0 && vo.audio_base64.length > maxChars) return null;

  const bin = deps.atob(vo.audio_base64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);

  const blob = new deps.Blob([bytes], { type: vo.content_type });
  const url = deps.createObjectURL(blob);
  return { url, contentType: vo.content_type };
}

export function createAudioFromVoiceOutputUsingGlobals(
  vo: VoiceOutput | null | undefined,
  opts?: { maxBase64Chars?: number }
): VoiceOutputAudio | null {
  if (typeof window === "undefined") return null;
  if (typeof window.atob !== "function") return null;
  if (typeof window.URL?.createObjectURL !== "function") return null;
  if (typeof Blob === "undefined") return null;

  return createAudioFromVoiceOutput(
    vo,
    {
      atob: window.atob.bind(window),
      Blob,
      createObjectURL: window.URL.createObjectURL.bind(window.URL),
    },
    opts
  );
}

export function safeRevokeObjectUrl(url: string | null | undefined): void {
  if (!url) return;
  try {
    URL.revokeObjectURL(url);
  } catch {
    // ignore
  }
}

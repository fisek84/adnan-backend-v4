import { useCallback, useEffect, useRef, useState } from 'react';

interface UseSpeechSynthesisReturn {
  speak: (text: string) => void;
  cancel: () => void;
  speaking: boolean;
  supported: boolean;
  /** Full list of browser voices (if any) */
  voices: SpeechSynthesisVoice[];
  /** Currently selected voice name (if any) */
  selectedVoiceName: string | null;
  /** Select voice by name (simple identifier for UI) */
  selectVoiceByName: (name: string | null) => void;
}

type SpeechOptions = {
  rate?: number;
  pitch?: number;
};

export const useSpeechSynthesis = (
  lang: string = 'en-US',
  options?: SpeechOptions,
): UseSpeechSynthesisReturn => {
  const [speaking, setSpeaking] = useState(false);
  const [supported, setSupported] = useState(false);
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([]);
  const [selectedVoiceName, setSelectedVoiceName] = useState<string | null>(null);
  const utteranceRef = useRef<SpeechSynthesisUtterance | null>(null);

  // Detect support + load voices (desktop & mobile where available)
  useEffect(() => {
    const isSupported = typeof window !== 'undefined' && 'speechSynthesis' in window;
    setSupported(isSupported);
    if (!isSupported) return;

    const loadVoices = () => {
      const list = window.speechSynthesis.getVoices?.() ?? [];
      setVoices(list);

      // If nothing selected yet, choose a reasonable default:
      if (!selectedVoiceName && list.length > 0) {
        const langPrefix = lang.slice(0, 2).toLowerCase();
        const preferred =
          list.find((v) => v.lang?.toLowerCase().startsWith(langPrefix)) ?? list[0];
        setSelectedVoiceName(preferred.name);
      }
    };

    loadVoices();

    // Some browsers load voices async
    const handler = () => loadVoices();
    window.speechSynthesis.onvoiceschanged = handler;

    return () => {
      if (window.speechSynthesis.onvoiceschanged === handler) {
        window.speechSynthesis.onvoiceschanged = null;
      }
    };
  }, [lang, selectedVoiceName]);

  const speak = useCallback(
    (text: string) => {
      if (!supported || !text.trim()) return;

      // Cancel any ongoing speech
      window.speechSynthesis.cancel();

      const utterance = new SpeechSynthesisUtterance(text);
      utterance.rate = options?.rate ?? 1.0;
      utterance.pitch = options?.pitch ?? 1.0;
      utterance.volume = 1.0;
      utterance.lang = lang;

      // Try to respect selected voice (male/female/etc.),
      // but always fall back gracefully.
      if (voices.length > 0) {
        const langLower = lang.toLowerCase();
        let prefixes = [langLower.slice(0, 2)];
        // Bosanski / Croatian / Serbian cluster: prefer any ex-Yu voice
        if (langLower.startsWith("bs") || langLower.startsWith("hr") || langLower.startsWith("sr")) {
          prefixes = ["bs", "hr", "sr", "sh"];
        }
        const byName = selectedVoiceName
          ? voices.find((v) => v.name === selectedVoiceName)
          : undefined;
        const byLang = voices.find((v) => {
          const vlang = v.lang?.toLowerCase() || "";
          return prefixes.some((p) => vlang.startsWith(p));
        });
        utterance.voice = byName ?? byLang ?? voices[0];
      }

      utterance.onstart = () => setSpeaking(true);
      utterance.onend = () => setSpeaking(false);
      utterance.onerror = () => setSpeaking(false);

      utteranceRef.current = utterance;
      window.speechSynthesis.speak(utterance);
    },
    [supported, lang, voices, selectedVoiceName, options?.rate, options?.pitch]
  );

  const cancel = useCallback(() => {
    if (!supported) return;
    window.speechSynthesis.cancel();
    setSpeaking(false);
  }, [supported]);

  const selectVoiceByName = useCallback((name: string | null) => {
    setSelectedVoiceName(name);
  }, []);

  return { speak, cancel, speaking, supported, voices, selectedVoiceName, selectVoiceByName };
};

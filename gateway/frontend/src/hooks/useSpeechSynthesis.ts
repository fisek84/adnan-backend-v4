import { useCallback, useEffect, useRef, useState } from 'react';

interface UseSpeechSynthesisReturn {
  speak: (text: string) => void;
  cancel: () => void;
  speaking: boolean;
  supported: boolean;
}

export const useSpeechSynthesis = (lang: string = 'en-US'): UseSpeechSynthesisReturn => {
  const [speaking, setSpeaking] = useState(false);
  const [supported, setSupported] = useState(false);
  const utteranceRef = useRef<SpeechSynthesisUtterance | null>(null);

  useEffect(() => {
    const isSupported = 'speechSynthesis' in window;
    setSupported(isSupported);
  }, []);

  const speak = useCallback((text: string) => {
    if (!supported || !text.trim()) return;

    // Cancel any ongoing speech
    window.speechSynthesis.cancel();

    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 1.0;
    utterance.pitch = 1.0;
    utterance.volume = 1.0;
    utterance.lang = lang;

    utterance.onstart = () => setSpeaking(true);
    utterance.onend = () => setSpeaking(false);
    utterance.onerror = () => setSpeaking(false);

    utteranceRef.current = utterance;
    window.speechSynthesis.speak(utterance);
  }, [supported, lang]);

  const cancel = useCallback(() => {
    if (!supported) return;
    window.speechSynthesis.cancel();
    setSpeaking(false);
  }, [supported]);

  return { speak, cancel, speaking, supported };
};

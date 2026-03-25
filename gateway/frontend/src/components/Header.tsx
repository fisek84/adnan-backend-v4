import React, { useEffect, useRef, useState } from 'react';
import { useTheme } from '../contexts/ThemeContext';

interface HeaderProps {
  title?: string;
  subtitle?: string;
  onVoiceToggle?: () => void;
  voiceListening?: boolean;
  voiceSupported?: boolean;
  onStopCurrent?: () => void;
  showStop?: boolean;
  onJumpToLatest?: () => void;
  showJump?: boolean;
  disabled?: boolean;
  // Language + voice controls for TTS/STT
  language?: string;
  onLanguageChange?: (lang: string) => void;
  ttsVoices?: { value: string; label: string }[];
  selectedTtsVoiceId?: string;
  onTtsVoiceChange?: (id: string) => void;
  enableVoice?: boolean;
  onEnableVoiceChange?: (value: boolean) => void;
  enableTTS?: boolean;
  onEnableTTSChange?: (value: boolean) => void;
  autoSpeak?: boolean;
  onAutoSpeakChange?: (value: boolean) => void;
  autoSendOnVoiceFinal?: boolean;
  onAutoSendOnVoiceFinalChange?: (value: boolean) => void;
  speechRate?: number;
  onSpeechRateChange?: (value: number) => void;
  speechPitch?: number;
  onSpeechPitchChange?: (value: number) => void;
  // Backend output language (Bosanski / English)
  outputLanguage?: string;
  onOutputLanguageChange?: (value: string) => void;

  // Backend per-agent voice profiles (resolved server-side)
  backendVoiceAgents?: { agent_id: string; name: string }[];
  backendVoicePresets?: {
    preset_id: string;
    label: string;
    vendor_voice: string;
    gender: string;
    languages: string[];
  }[];
  backendVoiceTargetAgentId?: string;
  onBackendVoiceTargetAgentIdChange?: (agentId: string) => void;
  backendVoiceProfile?: { language?: string; gender?: string; preset_id?: string };
  onBackendVoiceProfileChange?: (patch: {
    language?: string;
    gender?: string;
    preset_id?: string;
  }) => void;
}

export const Header: React.FC<HeaderProps> = ({
  title = "Adnan AI",
  subtitle = "CEO Assistant",
  onVoiceToggle,
  voiceListening = false,
  voiceSupported = false,
  onStopCurrent,
  showStop = false,
  onJumpToLatest,
  showJump = false,
  disabled = false,
  language,
  onLanguageChange,
  ttsVoices,
  selectedTtsVoiceId,
  onTtsVoiceChange,
  enableVoice,
  onEnableVoiceChange,
  enableTTS,
  onEnableTTSChange,
  autoSpeak,
  onAutoSpeakChange,
  autoSendOnVoiceFinal,
  onAutoSendOnVoiceFinalChange,
  speechRate,
  onSpeechRateChange,
  speechPitch,
  onSpeechPitchChange,
  outputLanguage,
  onOutputLanguageChange,

  backendVoiceAgents,
  backendVoicePresets,
  backendVoiceTargetAgentId,
  onBackendVoiceTargetAgentIdChange,
  backendVoiceProfile,
  onBackendVoiceProfileChange,
}) => {
  const { theme, toggleTheme } = useTheme();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const settingsRootRef = useRef<HTMLDivElement | null>(null);

  // Close on outside click + ESC (minimal, production-safe).
  useEffect(() => {
    if (!settingsOpen) return;
    const onPointerDown = (ev: MouseEvent | TouchEvent) => {
      const root = settingsRootRef.current;
      if (!root) return;
      const target = ev.target as Node | null;
      if (!target) return;
      if (root.contains(target)) return;
      setSettingsOpen(false);
    };
    const onKeyDown = (ev: KeyboardEvent) => {
      if (ev.key === 'Escape') setSettingsOpen(false);
    };

    document.addEventListener('mousedown', onPointerDown as any, true);
    document.addEventListener('touchstart', onPointerDown as any, true);
    document.addEventListener('keydown', onKeyDown, true);
    return () => {
      document.removeEventListener('mousedown', onPointerDown as any, true);
      document.removeEventListener('touchstart', onPointerDown as any, true);
      document.removeEventListener('keydown', onKeyDown, true);
    };
  }, [settingsOpen]);

  const showFallbackVoiceControls = !!(
    ttsVoices &&
    ttsVoices.length > 0 &&
    typeof onTtsVoiceChange === 'function'
  );
  const showFallbackSliders = showFallbackVoiceControls && (
    enableTTS === false || !!(selectedTtsVoiceId && selectedTtsVoiceId.trim())
  );

  const showBackendVoiceProfiles =
    typeof onBackendVoiceProfileChange === 'function' &&
    typeof onBackendVoiceTargetAgentIdChange === 'function' &&
    Array.isArray(backendVoiceAgents) &&
    backendVoiceAgents.length > 0 &&
    Array.isArray(backendVoicePresets) &&
    backendVoicePresets.length > 0;

  return (
    <header className="ceoHeader">
      <div className="ceoHeaderTitleRow">
        <div>
          <div className="ceoHeaderTitle">{title}</div>
          <div className="ceoHeaderSubtitle">{subtitle}</div>
        </div>
        <div className="ceoHeaderActions">
          {showJump && onJumpToLatest && (
            <button 
              className="ceoHeaderButton"
              onClick={onJumpToLatest}
              aria-label="Jump to latest message"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 14l-7 7m0 0l-7-7m7 7V3" />
              </svg>
            </button>
          )}

          {voiceSupported && onVoiceToggle && (
            <button
              className={`ceoHeaderButton ${voiceListening ? 'voice-active' : ''}`}
              onClick={onVoiceToggle}
              disabled={disabled}
              title={voiceListening ? "Stop voice input" : "Start voice input"}
              aria-label={voiceListening ? "Stop voice input" : "Start voice input"}
            >
              {voiceListening ? (
                <svg className="w-4 h-4 animate-pulse" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z"/>
                  <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"/>
                </svg>
              ) : (
                <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z"/>
                  <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"/>
                </svg>
              )}
            </button>
          )}

          <button
            className="ceoHeaderButton"
            onClick={toggleTheme}
            title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
            aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
          >
            {theme === 'dark' ? (
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
              </svg>
            ) : (
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
              </svg>
            )}
          </button>

          {autoSendOnVoiceFinal && (
            <div
              className="ceoHeaderFullVoice"
              title="Full voice mode: auto-send after pause + auto-play replies"
            >
              <span className="ceoHeaderFullVoiceDot" />
              <span className="ceoHeaderFullVoiceText">Full voice</span>
            </div>
          )}

          {/* Discreet settings menu (language, voice) */}
          {(onLanguageChange || (ttsVoices && ttsVoices.length > 0 && onTtsVoiceChange)) && (
            <div className="ceoHeaderSettingsContainer" ref={settingsRootRef}>
              <button
                className="ceoHeaderButton"
                type="button"
                onClick={() => setSettingsOpen((o) => !o)}
                aria-haspopup="true"
                aria-expanded={settingsOpen}
                aria-label="Open voice and language settings"
              >
                <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="3" />
                  <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 01-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 008.4 19a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 11-2.83-2.83l.06-.06A1.65 1.65 0 004 15.4a1.65 1.65 0 00-1.51-1H2a2 2 0 010-4h.09A1.65 1.65 0 004 8.6a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 112.83-2.83l.06.06A1.65 1.65 0 008.6 4a1.65 1.65 0 001-1.51V2a2 2 0 014 0v.09A1.65 1.65 0 0015.4 4a1.65 1.65 0 001.82-.33l.06-.06a2 2 0 112.83 2.83l-.06.06A1.65 1.65 0 0019 8.6a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09A1.65 1.65 0 0019.4 15z" />
                </svg>
              </button>

              {settingsOpen && (
                <div className="ceoHeaderSettingsPanel">
                  {onEnableVoiceChange !== undefined && (
                    <label className="ceoHeaderSettingsRow">
                      <span>Voice input</span>
                      <input
                        type="checkbox"
                        checked={enableVoice !== false}
                        onChange={(e) => onEnableVoiceChange(e.target.checked)}
                      />
                    </label>
                  )}

                  {onEnableTTSChange !== undefined && (
                    <label className="ceoHeaderSettingsRow">
                      <span>Voice output (backend primary)</span>
                      <input
                        type="checkbox"
                        checked={enableTTS !== false}
                        onChange={(e) => onEnableTTSChange(e.target.checked)}
                      />
                    </label>
                  )}

                  {showBackendVoiceProfiles && (
                    <>
                      <label className="ceoHeaderSettingsRow">
                        <span>Backend voice agent</span>
                        <select
                          className="ceoHeaderSelect"
                          value={backendVoiceTargetAgentId || ''}
                          onChange={(e) => onBackendVoiceTargetAgentIdChange(e.target.value)}
                        >
                          {backendVoiceAgents!.map((a) => (
                            <option key={a.agent_id} value={a.agent_id}>
                              {a.name}
                            </option>
                          ))}
                        </select>
                      </label>

                      <label className="ceoHeaderSettingsRow">
                        <span>Backend voice language</span>
                        <select
                          className="ceoHeaderSelect"
                          value={(backendVoiceProfile?.language as any) || ''}
                          onChange={(e) => onBackendVoiceProfileChange({ language: e.target.value || undefined })}
                        >
                          <option value="">Default</option>
                          <option value="bs">Bosanski</option>
                          <option value="hr">Hrvatski</option>
                          <option value="sr">Srpski</option>
                          <option value="en">English</option>
                          <option value="de">Deutsch</option>
                        </select>
                      </label>

                      <label className="ceoHeaderSettingsRow">
                        <span>Backend voice gender</span>
                        <select
                          className="ceoHeaderSelect"
                          value={(backendVoiceProfile?.gender as any) || ''}
                          onChange={(e) => onBackendVoiceProfileChange({ gender: e.target.value || undefined })}
                        >
                          <option value="">Default</option>
                          <option value="male">Male</option>
                          <option value="female">Female</option>
                          <option value="neutral">Neutral</option>
                        </select>
                      </label>

                      <label className="ceoHeaderSettingsRow">
                        <span>Backend voice preset</span>
                        <select
                          className="ceoHeaderSelect"
                          value={(backendVoiceProfile?.preset_id as any) || ''}
                          onChange={(e) => onBackendVoiceProfileChange({ preset_id: e.target.value || undefined })}
                        >
                          <option value="">Default</option>
                          {backendVoicePresets!.map((p) => (
                            <option key={p.preset_id} value={p.preset_id}>
                              {p.label} ({p.gender})
                            </option>
                          ))}
                        </select>
                      </label>
                    </>
                  )}

                  {onAutoSpeakChange !== undefined && (
                    <label className="ceoHeaderSettingsRow">
                      <span>Auto-play replies</span>
                      <input
                        type="checkbox"
                        checked={autoSpeak === true}
                        onChange={(e) => onAutoSpeakChange(e.target.checked)}
                      />
                    </label>
                  )}

                  {onAutoSendOnVoiceFinalChange !== undefined && (
                    <label className="ceoHeaderSettingsRow">
                      <span>Auto-send after pause (voice)</span>
                      <input
                        type="checkbox"
                        checked={autoSendOnVoiceFinal === true}
                        onChange={(e) => onAutoSendOnVoiceFinalChange(e.target.checked)}
                      />
                    </label>
                  )}

                  {onLanguageChange && (
                    <label className="ceoHeaderSettingsRow">
                      <span>Jezik / Language</span>
                      <select
                        className="ceoHeaderSelect"
                        value={language || 'en-US'}
                        onChange={(e) => onLanguageChange(e.target.value)}
                      >
                        <option value="en-US">English (US)</option>
                        <option value="en-GB">English (UK)</option>
                        <option value="bs-BA">Bosanski</option>
                        <option value="hr-HR">Hrvatski</option>
                        <option value="sr-RS">Srpski</option>
                        <option value="de-DE">Deutsch</option>
                      </select>
                    </label>
                  )}

                  {onOutputLanguageChange && (
                    <label className="ceoHeaderSettingsRow">
                      <span>Output language</span>
                      <select
                        className="ceoHeaderSelect"
                        value={outputLanguage || 'bs'}
                        onChange={(e) => onOutputLanguageChange(e.target.value)}
                      >
                        <option value="bs">Bosanski</option>
                        <option value="hr">Hrvatski</option>
                        <option value="sr">Srpski</option>
                        <option value="en">English</option>
                        <option value="de">Deutsch</option>
                      </select>
                    </label>
                  )}

                  {showFallbackVoiceControls && (
                    <label className="ceoHeaderSettingsRow">
                      <span>Fallback voice (browser only; used only if backend audio is missing)</span>
                      <select
                        className="ceoHeaderSelect"
                        value={selectedTtsVoiceId || ''}
                        onChange={(e) => onTtsVoiceChange(e.target.value || '')}
                      >
                        <option value="">Default</option>
                        {ttsVoices.map((v) => (
                          <option key={v.value} value={v.value}>
                            {v.label}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}

                  {showFallbackSliders && onSpeechRateChange && speechRate !== undefined && (
                    <label className="ceoHeaderSettingsRow ceoHeaderSettingsRow-stack">
                      <span>Fallback speech rate</span>
                      <input
                        type="range"
                        min={0.6}
                        max={1.8}
                        step={0.05}
                        value={speechRate}
                        onChange={(e) => onSpeechRateChange(parseFloat(e.target.value))}
                      />
                    </label>
                  )}

                  {showFallbackSliders && onSpeechPitchChange && speechPitch !== undefined && (
                    <label className="ceoHeaderSettingsRow ceoHeaderSettingsRow-stack">
                      <span>Fallback pitch</span>
                      <input
                        type="range"
                        min={0.6}
                        max={1.6}
                        step={0.05}
                        value={speechPitch}
                        onChange={(e) => onSpeechPitchChange(parseFloat(e.target.value))}
                      />
                    </label>
                  )}
                </div>
              )}
            </div>
          )}

          {showStop && onStopCurrent && (
            <button 
              className="ceoHeaderButton ceoHeaderButton-stop"
              onClick={onStopCurrent}
              aria-label="Stop current action"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          )}
        </div>
      </div>
    </header>
  );
};

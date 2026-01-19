import React from 'react';
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
}) => {
  const { theme, toggleTheme } = useTheme();

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

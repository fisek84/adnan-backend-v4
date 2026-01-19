# Voice Recognition & Enhanced UI Features

This document describes the new features added to the Adnan AI frontend application.

## Features Added

### 1. Voice Recognition (Web Speech API)
- **Voice Input**: Click the microphone button in the header or composer to start voice recognition
- **Real-time Transcription**: Voice is transcribed in real-time to the text input field
- **Visual Feedback**: Active listening state is indicated with a pulsing microphone icon
- **Language Support**: Configured for Bosnian (bs-BA) but can be easily changed
- **Browser Compatibility**: Works in Chrome, Edge, and Safari (with webkit prefix)

### 2. Voice Synthesis (Text-to-Speech)
- **Auto-Speak**: Optional automatic speaking of system responses (disabled by default)
- **Manual Speak**: 🔊 button appears on system messages to speak them on demand
- **Natural Voice**: Uses browser's built-in speech synthesis engine
- **Configurable**: Can be enabled/disabled via component props

### 3. Dark/Light Mode Theme Toggle
- **Smooth Transitions**: All colors transition smoothly when switching themes (0.3s ease)
- **Persistent**: Theme preference is saved to localStorage
- **System Preference**: Defaults to system preference on first load
- **Complete Coverage**: All UI elements adapt to the selected theme
- **Toggle Button**: Sun/moon icon in the header for easy switching

### 4. Modern UI with Tailwind CSS
- **Tailwind CSS v4**: Latest version with PostCSS integration
- **Custom Configuration**: Tailwind configured with dark mode class strategy
- **Utility Classes**: Available throughout the application
- **Custom Colors**: Primary green color palette defined
- **Forms Plugin**: Enhanced form styling with @tailwindcss/forms

### 5. Enhanced Typography
- **Inter Font**: Google Fonts Inter variable font for modern, clean typography
- **Font Weights**: Support for weights 300-900
- **Optimized Loading**: Preconnect to Google Fonts for better performance
- **Fallback Fonts**: Comprehensive fallback stack for compatibility

### 6. Responsive Design
- **Mobile-First**: Optimized for mobile devices (320px and up)
- **Breakpoints**:
  - Mobile: < 480px (single column, larger touch targets)
  - Tablet: 481px - 768px (adapted layout)
  - Desktop: > 768px (full layout)
- **Touch-Friendly**: Minimum 44px touch targets on mobile
- **Viewport Optimization**: Proper viewport meta tag prevents zoom on iOS
- **Flexible Layouts**: Grid and flexbox layouts adapt seamlessly

## Component Architecture

### New Components

#### `ThemeContext.tsx`
- React Context for managing theme state
- Provides `theme` (current theme) and `toggleTheme` (switch function)
- Handles localStorage persistence
- Syncs with system preferences

#### `Header.tsx`
- Reusable header component with all controls
- Props for voice toggle, theme toggle, stop button, and jump to latest
- Icon-based buttons with proper ARIA labels
- Responsive layout

#### `useSpeechSynthesis.ts`
- Custom React hook for Text-to-Speech
- Provides `speak()`, `cancel()`, `speaking`, and `supported` states
- Handles browser compatibility
- Cleanup on unmount

## Usage

### Enable Voice Features

```tsx
<CeoChatbox
  ceoCommandUrl="/api/chat"
  enableVoice={true}        // Enable voice input
  enableTTS={true}          // Enable text-to-speech
  autoSpeak={false}         // Auto-speak system responses
/>
```

### Theme Toggle

The theme toggle is automatically available in the header. Users can:
1. Click the sun/moon icon to switch themes
2. Theme preference is saved automatically
3. Reloading the page preserves the selection

## Browser Compatibility

### Voice Recognition
- ✅ Chrome/Edge (full support)
- ✅ Safari (webkit prefix)
- ❌ Firefox (not supported yet)

### Voice Synthesis
- ✅ Chrome/Edge (full support)
- ✅ Safari (full support)
- ✅ Firefox (full support)

### Dark/Light Mode
- ✅ All modern browsers (CSS variables + class strategy)

### Responsive Design
- ✅ All modern browsers and devices

## Styling Guide

### CSS Variables (Dark Mode)
```css
--ceo-bg: #0b0f14
--ceo-text: rgba(255,255,255,0.92)
--ceo-border: rgba(255,255,255,0.08)
```

### CSS Variables (Light Mode)
```css
--ceo-bg: #f8fafc
--ceo-text: rgba(0,0,0,0.92)
--ceo-border: rgba(0,0,0,0.10)
```

All variables transition smoothly when theme changes.

## Performance Optimizations

1. **Lazy Font Loading**: Google Fonts with preconnect
2. **CSS Transitions**: Hardware-accelerated (transform, opacity)
3. **Code Splitting**: Vite automatically splits code
4. **Minimal Bundle**: Only necessary Tailwind utilities included
5. **Cached Theme**: localStorage prevents theme flash on load

## Accessibility

- ✅ ARIA labels on all interactive elements
- ✅ Keyboard navigation support
- ✅ Screen reader friendly
- ✅ Sufficient color contrast in both themes
- ✅ Focus indicators on interactive elements
- ✅ Semantic HTML structure

## Future Enhancements

Potential improvements for future versions:
- Voice command shortcuts (e.g., "Send message")
- Multiple language support for voice recognition
- Voice speed/pitch controls for TTS
- Custom theme colors
- Animation preferences (reduced motion)
- High contrast mode
- Larger text option for accessibility

# Quick Feature Guide

## Where to Find Each Feature

### 1. 🎤 Voice Recognition

**Location:** Top-right corner of the header (microphone icon)

**How to use:**
1. Click the microphone icon
2. Allow microphone permissions when prompted
3. Speak your command
4. The text will appear in the input field
5. Click again to stop listening

**Visual indicator:** Icon pulses when actively listening

---

### 2. 🌙/☀️ Dark/Light Mode Toggle

**Location:** Top-right corner of the header (next to microphone, sun/moon icon)

**How to use:**
1. Click the sun icon (in dark mode) to switch to light mode
2. Click the moon icon (in light mode) to switch to dark mode
3. Your preference is automatically saved

**Persistence:** Reloading the page keeps your selected theme

---

### 3. 🔊 Text-to-Speech (TTS)

**Location:** On each system message (response from the AI)

**How to use:**
1. Wait for a system response to appear
2. Click the 🔊 (speaker) icon on the message
3. The text will be read aloud
4. Click again to stop

**Note:** Only appears on system/assistant messages, not your own messages

---

### 4. 📱 Responsive Design

**Automatic:** No action needed

**What happens:**
- **Mobile** (< 480px): Touch-optimized layout, larger buttons
- **Tablet** (481-768px): Adapted two-column layout
- **Desktop** (> 768px): Full layout with all features

**Test it:** Resize your browser window to see the layout adapt

---

## Keyboard Shortcuts

- **Voice Input:** No keyboard shortcut (click required for security)
- **Theme Toggle:** No keyboard shortcut (click required)
- **Send Message:** `Enter` in the text input

---

## Browser Support

| Feature | Chrome | Edge | Safari | Firefox |
|---------|--------|------|--------|---------|
| Voice Recognition | ✅ | ✅ | ✅ | ❌ |
| Text-to-Speech | ✅ | ✅ | ✅ | ✅ |
| Dark/Light Mode | ✅ | ✅ | ✅ | ✅ |
| Responsive Design | ✅ | ✅ | ✅ | ✅ |

**Note:** Voice Recognition requires HTTPS (or localhost for development)

---

## Quick Troubleshooting

**Can't see the buttons?**
- Hard refresh: `Ctrl+Shift+R` (Windows/Linux) or `Cmd+Shift+R` (Mac)
- Try incognito/private mode
- Check browser console (F12) for errors

**Microphone doesn't work?**
- Allow microphone permissions in browser
- Use Chrome, Edge, or Safari (Firefox not supported)
- Ensure you're on HTTPS (or localhost)

**Theme doesn't persist?**
- Check if browser allows localStorage
- Try clearing localStorage: `localStorage.clear()` in console

**TTS doesn't work?**
- Check browser audio is not muted
- Try clicking the speaker icon multiple times
- Check browser console for errors

---

## Component Props (for developers)

```tsx
<CeoChatbox
  ceoCommandUrl="/api/chat"
  approveUrl="/api/ai-ops/approval/approve"
  executeRawUrl="/api/execute/raw"
  enableVoice={true}        // Toggle voice recognition
  enableTTS={true}           // Toggle text-to-speech
  autoSpeak={false}          // Auto-speak responses (default: false)
  voiceLang="en-US"          // Language for voice/TTS (default: 'en-US')
/>
```

**Available languages for voice:**
- `en-US` - English (US)
- `en-GB` - English (UK)
- `bs-BA` - Bosnian
- `hr-HR` - Croatian
- `sr-RS` - Serbian
- And many more...

---

For detailed deployment and troubleshooting, see [DEPLOYMENT.md](./DEPLOYMENT.md)

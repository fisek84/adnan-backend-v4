# Frontend Deployment Guide

## Features Included

This React frontend includes the following features:

### 1. 🎤 Voice Recognition (Web Speech API)
- **Location**: Microphone button in the top-right header
- **How to use**: Click the microphone icon to start voice input
- **Visual indicator**: The icon pulses when actively listening
- **Browser support**: Chrome, Edge, Safari (with webkit prefix)

### 2. 🔊 Text-to-Speech (TTS)
- **Location**: Speaker icons appear on system messages
- **How to use**: Click the 🔊 icon on any system message to hear it spoken
- **Configuration**: Enabled by default, can be configured via `enableTTS` prop
- **Browser support**: All modern browsers

### 3. 🌓 Dark/Light Mode Toggle
- **Location**: Sun/Moon icon button in the top-right header
- **How to use**: Click to switch between dark and light themes
- **Persistence**: Your preference is saved to localStorage
- **Default**: Follows your system preference on first load

### 4. 📱 Responsive Design
- **Mobile**: < 480px (optimized for touch, larger targets)
- **Tablet**: 481px - 768px (adapted layout)
- **Desktop**: > 768px (full layout with all features)

## Verifying Deployment on Render

### Check if New Build is Deployed

1. **Check Build Logs on Render**
   - Go to your Render dashboard
   - Click on your service
   - Go to "Events" or "Logs" tab
   - Look for recent deployment logs showing:
     ```
     ===== FRONTEND DIST LIST =====
     ```
   - This confirms the frontend was built

2. **Clear Browser Cache**
   - The most common issue is browser caching
   - **Hard Refresh**:
     - **Windows/Linux**: `Ctrl + Shift + R` or `Ctrl + F5`
     - **Mac**: `Cmd + Shift + R`
   - **Or clear cache manually**:
     - Chrome/Edge: Settings → Privacy → Clear browsing data → Cached images and files
     - Firefox: Settings → Privacy → Clear Data → Cached Web Content
     - Safari: Develop → Empty Caches

3. **Check Build Timestamp**
   - Open browser DevTools (F12)
   - Go to Network tab
   - Refresh the page
   - Look for `index.html` request
   - Check the "Response Headers" for `last-modified` date
   - Compare with your latest deployment time

4. **Verify Features are Loaded**
   - Open browser DevTools (F12)
   - Go to Console tab
   - Run: `document.querySelector('[aria-label*="voice"]')`
   - If it returns an element, voice features are loaded
   - Run: `document.documentElement.classList.contains('light') || document.documentElement.classList.contains('dark')`
   - Should return `true` if theme system is loaded

### Force Render to Rebuild

If cache clearing doesn't work:

1. **Trigger Manual Deploy**
   - Go to Render dashboard
   - Click "Manual Deploy" → "Deploy latest commit"
   - This forces a fresh build

2. **Add Cache Busting**
   - Make a small change (like adding a comment)
   - Commit and push
   - Render will rebuild automatically

## Local Development

```bash
# Install dependencies
cd gateway/frontend
npm install

# Start dev server
npm run dev
# Opens at http://localhost:5173

# Build for production
npm run build
# Output in dist/ folder
```

## Production Build

The Dockerfile handles frontend build automatically:

```dockerfile
# Stage 1: Build frontend
FROM node:20-alpine AS frontend-build
WORKDIR /app/gateway/frontend
RUN npm ci && npm run build

# Stage 2: Serve via Python backend
FROM python:3.11-slim
COPY --from=frontend-build /app/gateway/frontend/dist ./gateway/frontend/dist
```

## Troubleshooting

### "I don't see the new features"

1. **Clear browser cache** (see above)
2. **Check you're on the right URL** (not localhost, but your Render URL)
3. **Verify deployment completed** on Render dashboard
4. **Check browser console** for JavaScript errors
5. **Try incognito/private browsing mode** (bypasses cache)

### "Microphone button doesn't work"

1. **Check browser support**: Voice recognition only works in Chrome, Edge, Safari
2. **Allow microphone permissions** when browser prompts
3. **Use HTTPS**: Voice API requires secure context (localhost or HTTPS)

### "Theme toggle doesn't work"

1. **Check browser console** for errors
2. **Verify localStorage is enabled** in browser settings
3. **Clear localStorage**: Run in console: `localStorage.clear()` then refresh

### "Features work locally but not on Render"

1. **Compare build output**:
   - Local: `npm run build` → check `dist/` folder
   - Render: Check build logs for FRONTEND DIST LIST
2. **Verify files are served**:
   - Visit: `https://your-app.onrender.com/`
   - Open DevTools → Sources tab
   - Check if `/assets/*.js` files are present
3. **Check gateway_server.py**:
   - Ensure StaticFiles is mounted: `app.mount("/", StaticFiles(...))`

## Screenshots

### Light Mode
![Light Mode](https://github.com/user-attachments/assets/01287446-7cad-4cbc-863d-a2fcb8ddd571)

### Dark Mode
![Dark Mode](https://github.com/user-attachments/assets/a73ce23f-9530-4594-b2ae-24081ef8cbd6)

## Features Location Reference

```
┌─────────────────────────────────────────────┐
│ CEO Console                    🎤  🌙/☀️    │  ← Voice + Theme Toggle
├─────────────────────────────────────────────┤
│                                             │
│           (Main Content Area)               │
│                                             │
├─────────────────────────────────────────────┤
│ Search Notion              [Search Box]    │
├─────────────────────────────────────────────┤
│ Write a CEO command...     [Voice] [Send]  │  ← Voice Button in Composer
└─────────────────────────────────────────────┘
```

## Support

If features still don't appear after following all troubleshooting steps:

1. Check Render deployment logs for errors
2. Verify build completed successfully
3. Check browser compatibility (use latest Chrome/Edge for best results)
4. Ensure JavaScript is enabled in browser

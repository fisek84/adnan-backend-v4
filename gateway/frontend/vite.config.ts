import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: path.resolve(__dirname, "../static"),
    emptyOutDir: false,
    rollupOptions: {
      input: path.resolve(__dirname, "src/main.tsx"),
      output: {
        entryFileNames: "ceo_chatbox.js",
        chunkFileNames: "ceo_chatbox.[hash].js",
        assetFileNames: "ceo_chatbox.[hash][extname]",
      },
    },
  },
});

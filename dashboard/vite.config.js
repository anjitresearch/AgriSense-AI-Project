import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
export default defineConfig({
    plugins: [react()],
    base: "./",
    server: {
        port: 5173,
        proxy: {
            // Proxy API calls to EDGE-BRAIN™ FastAPI during development
            "/api/edge": {
                target: "http://localhost:8000",
                changeOrigin: true,
                rewrite: (path) => path.replace(/^\/api\/edge/, ""),
            },
            // Proxy to SKYWATCH-H™ Node.js API
            "/api/skywatch": {
                target: "http://localhost:3001",
                changeOrigin: true,
                rewrite: (path) => path.replace(/^\/api\/skywatch/, ""),
            },
        },
    },
});

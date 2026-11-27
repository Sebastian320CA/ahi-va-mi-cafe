import type { NextConfig } from "next";

// The panel calls the API through same-origin rewrites so the session cookie stays httpOnly.
// BACKEND_INTERNAL_URL is server-side only and never exposed to the browser.
const backend = process.env.BACKEND_INTERNAL_URL ?? "http://localhost:8000";

const config: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
};

export default config;

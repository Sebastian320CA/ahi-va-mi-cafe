import type { NextConfig } from "next";

// The panel calls the API through same-origin rewrites so the session cookie stays httpOnly.
// BACKEND_INTERNAL_URL is server-side only and never exposed to the browser.
// On Vercel the panel is useless without a reachable API: fail the build instead of shipping
// rewrites that point to localhost (which shows up as "Error 404" on the login form).
if (process.env.VERCEL && !process.env.BACKEND_INTERNAL_URL) {
  throw new Error(
    "BACKEND_INTERNAL_URL is not set. Add it in Vercel > Settings > Environment Variables " +
      "(public URL of the deployed backend, without trailing slash) and redeploy.",
  );
}

const backend = (process.env.BACKEND_INTERNAL_URL ?? "http://localhost:8000").replace(/\/+$/, "");

const config: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
};

export default config;

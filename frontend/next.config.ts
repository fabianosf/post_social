import type { NextConfig } from "next";

const FLASK_URL = process.env.FLASK_URL ?? "http://localhost:8095";

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    return [
      { source: "/api/:path*",     destination: `${FLASK_URL}/api/:path*` },
      { source: "/uploads/:path*", destination: `${FLASK_URL}/uploads/:path*` },
    ];
  },
  images: {
    remotePatterns: [{ protocol: "https", hostname: "**" }],
  },
};

export default nextConfig;

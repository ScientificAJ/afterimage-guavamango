import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  agentRules: false,
  allowedDevOrigins: ["127.0.0.1"],
  reactStrictMode: true,
  poweredByHeader: false,
};

export default nextConfig;

import type { NextConfig } from "next";

const config: NextConfig = {
  experimental: { optimizePackageImports: ["lucide-react"] },
};

export default config;

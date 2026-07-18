import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  // Avoid turbopack-only production builds in Docker (more portable).
  // `pnpm build` uses webpack unless --turbopack is passed.
};

export default nextConfig;

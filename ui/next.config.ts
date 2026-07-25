import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  output: "standalone",
  // Monorepo: root has package-lock.json; ui has pnpm-lock.yaml.
  outputFileTracingRoot: path.join(process.cwd(), ".."),
  transpilePackages: ["@fae/client"],
};

export default nextConfig;

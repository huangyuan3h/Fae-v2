import type { NextConfig } from "next";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const nextConfig: NextConfig = {
  output: "standalone",
  // Monorepo: root has package-lock.json; ui has pnpm-lock.yaml.
  outputFileTracingRoot: path.join(__dirname, ".."),
  transpilePackages: ["@fae/client"],
};

export default nextConfig;

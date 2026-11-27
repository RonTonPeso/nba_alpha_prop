import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  // Parent home has a pnpm-lock.yaml; pin tracing to this app so static
  // chunks resolve from frontend/.next instead of a wrong workspace root.
  outputFileTracingRoot: path.join(__dirname),
};

export default nextConfig;

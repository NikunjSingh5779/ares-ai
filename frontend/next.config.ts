import { type NextConfig } from "next";

const nextConfig: NextConfig = {
  output: process.env.NEXT_STANDALONE !== "false" ? "standalone" : undefined,
  /* API fetches go directly to the backend at localhost:8000 */
};

export default nextConfig;

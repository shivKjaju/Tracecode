/** @type {import('next').NextConfig} */

const IS_EXPORT = process.env.NEXT_EXPORT === "1";

const nextConfig = {
  // Static export for serving from FastAPI (set NEXT_EXPORT=1 for prod build)
  ...(IS_EXPORT ? { output: "export", trailingSlash: true } : {}),

  // During `next dev`, proxy /api/* to the FastAPI server (ignored in export mode)
  ...(!IS_EXPORT
    ? {
        async rewrites() {
          return [
            {
              source: "/api/:path*",
              destination: "http://127.0.0.1:7842/api/:path*",
            },
          ];
        },
      }
    : {}),
};

module.exports = nextConfig;

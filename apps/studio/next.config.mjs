/** @type {import('next').NextConfig} */
const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "same-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];
export default {
  reactStrictMode: true,
  poweredByHeader: false,
  output: "standalone",
  async headers() { return [{ source: "/(.*)", headers: securityHeaders }]; },
};

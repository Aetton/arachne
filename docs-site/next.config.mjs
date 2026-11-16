import { createMDX } from 'fumadocs-mdx/next';

const basePath = process.env.DOCS_BASE_PATH || '';

/** @type {import('next').NextConfig} */
const config = {
  env: { NEXT_PUBLIC_DOCS_BASE_PATH: basePath },
  output: 'export',
  trailingSlash: true,
  basePath,
  reactStrictMode: true,
  images: { unoptimized: true },
};

export default createMDX()(config);

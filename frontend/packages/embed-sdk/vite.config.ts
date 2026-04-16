import { defineConfig } from 'vite';

export default defineConfig({
  build: {
    lib: {
      entry: 'src/index.ts',
      name: 'AsEmbed',
      fileName: 'as-embed',
      formats: ['iife'],
    },
    outDir: 'dist',
    rollupOptions: {
      output: { inlineDynamicImports: true },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
  },
});

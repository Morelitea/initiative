import { defineConfig } from "orval";

export default defineConfig({
  initiative: {
    input: {
      target: "./openapi.json",
    },
    output: {
      target: "./src/api/generated",
      client: "react-query",
      httpClient: "axios",
      mode: "tags-split",
      clean: true,
      indexFiles: false,
      // Orval reads tsconfig.json and writes `.ts` into the client's imports when
      // it allows them, which it does for lib/templates' compiler (the Vite
      // config runs that in Node). The client keeps its imports as they were.
      tsconfig: {
        compilerOptions: { target: "es2020", module: "esnext", moduleResolution: "bundler" },
      },
      override: {
        mutator: {
          path: "./src/api/mutator.ts",
          name: "apiMutator",
        },
        query: {
          signal: true,
        },
        // One builder for every multipart body, rather than a loop written
        // into each endpoint.
        formData: {
          path: "./src/api/formData.ts",
          name: "toFormData",
        },
      },
    },
  },
});

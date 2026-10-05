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

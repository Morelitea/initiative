import { defineConfig } from "orval";

export default defineConfig({
  initiative: {
    input: {
      target: "./openapi.json",
    },
    output: {
      target: "./src/api/generated",
      client: "react-query",
      mode: "tags-split",
      clean: true,
      headers: true,
      override: {
        mutator: {
          path: "./src/api/mutator.ts",
          name: "apiMutator",
        },
        query: {
          useQuery: true,
          useMutation: true,
          signal: true,
        },
      },
    },
  },
});

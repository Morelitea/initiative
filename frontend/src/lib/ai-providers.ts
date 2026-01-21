import type { AIProvider } from "@/types/api";

export const OPENAI_MODELS = [
  "gpt-4o",
  "gpt-4o-mini",
  "gpt-4-turbo",
  "gpt-4",
  "gpt-4-turbo-preview",
  "gpt-3.5-turbo",
  "o1",
  "o1-mini",
  "o1-preview",
];

export const ANTHROPIC_MODELS = [
  "claude-sonnet-4-20250514",
  "claude-3-5-sonnet-20241022",
  "claude-3-5-haiku-20241022",
  "claude-3-opus-20240229",
  "claude-3-sonnet-20240229",
  "claude-3-haiku-20240307",
];

export const DEFAULT_OLLAMA_URL = "http://localhost:11434";

export interface ProviderConfig {
  label: string;
  requiresApiKey: boolean;
  requiresBaseUrl: boolean;
  hasModelDropdown: boolean;
  defaultModels: string[];
  defaultBaseUrl?: string;
  modelPlaceholder?: string;
}

export const PROVIDER_CONFIGS: Record<AIProvider, ProviderConfig> = {
  openai: {
    label: "OpenAI",
    requiresApiKey: true,
    requiresBaseUrl: false,
    hasModelDropdown: true,
    defaultModels: OPENAI_MODELS,
  },
  anthropic: {
    label: "Anthropic",
    requiresApiKey: true,
    requiresBaseUrl: false,
    hasModelDropdown: true,
    defaultModels: ANTHROPIC_MODELS,
  },
  ollama: {
    label: "Ollama (Local)",
    requiresApiKey: false,
    requiresBaseUrl: true,
    hasModelDropdown: false,
    defaultModels: [],
    defaultBaseUrl: DEFAULT_OLLAMA_URL,
    modelPlaceholder: "llama2",
  },
  custom: {
    label: "Custom (OpenAI-compatible)",
    requiresApiKey: true,
    requiresBaseUrl: true,
    hasModelDropdown: false,
    defaultModels: [],
    modelPlaceholder: "model-name",
  },
};

export const getModelsForProvider = (
  provider: AIProvider | "",
  dynamicModels?: string[]
): string[] => {
  if (dynamicModels && dynamicModels.length > 0) {
    return dynamicModels;
  }
  if (!provider) {
    return [];
  }
  return PROVIDER_CONFIGS[provider]?.defaultModels ?? [];
};

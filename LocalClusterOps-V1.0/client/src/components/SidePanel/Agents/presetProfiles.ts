import type { AgentModelParameters } from 'librechat-data-provider';
import type { AgentForm, TAgentOption } from '~/common';
import { createProviderOption, getDefaultAgentFormValues } from '~/utils';

export type PresetProfile = {
  key: string;
  label: string;
  description: string;
  instructions: string;
  provider?: string;
  model?: string;
  model_parameters?: AgentModelParameters;
  category?: string;
};

export const PRESET_PROFILE_VALUE_PREFIX = '__assistant_preset__:';

export const presetProfiles: PresetProfile[] = [
  {
    key: 'general-assistant',
    label: 'General Assistant',
    description: 'Balanced default assistant behavior',
    category: 'development',
    instructions: [
      'You are a practical general-purpose assistant.',
      'Your lane: direct answers, everyday support, and clear next steps.',
      'Answer the user directly and clearly.',
      'Prefer concrete help over speculation.',
      'State uncertainty plainly when it matters.',
    ].join('\n'),
  },
  {
    key: 'code-assistant',
    label: 'Code Assistant',
    description: 'Implementation, debugging, and code review support',
    category: 'development',
    instructions: [
      'You are a coding and implementation assistant.',
      'Your lane: software engineering, debugging, refactoring, and practical code changes.',
      'Answer the user directly and clearly.',
      'Prefer concrete execution over speculation.',
      'Surface risks, regressions, and missing tests when they matter.',
    ].join('\n'),
  },
  {
    key: 'research-assistant',
    label: 'Research Assistant',
    description: 'Investigation, synthesis, and grounded reporting support',
    category: 'research',
    instructions: [
      'You are a research and synthesis assistant.',
      'Your lane: fact gathering, source comparison, summaries, and grounded reporting.',
      'Answer the user directly and clearly.',
      'Separate known facts from inference.',
      'Keep summaries concise, accurate, and useful.',
    ].join('\n'),
  },
  {
    key: 'operations-assistant',
    label: 'Operations Assistant',
    description: 'Planning, coordination, and operational support',
    category: 'operations',
    instructions: [
      'You are an operations support assistant.',
      'Your lane: planning, coordination, troubleshooting, and status tracking.',
      'Answer the user directly and clearly.',
      'Keep the response structured and action-oriented.',
      'Call out blockers and next steps plainly.',
    ].join('\n'),
  },
  {
    key: 'creative-assistant',
    label: 'Creative Assistant',
    description: 'Drafting, ideation, and content-shaping support',
    category: 'making',
    instructions: [
      'You are a creative support assistant.',
      'Your lane: drafting, brainstorming, editing, and shaping rough ideas into clearer outputs.',
      'Answer the user directly and clearly.',
      'Offer options when useful.',
      'Keep the work grounded in the user request.',
    ].join('\n'),
  },
];

export const getPresetProfileSelectValue = (key: string) => `${PRESET_PROFILE_VALUE_PREFIX}${key}`;

export const isPresetProfileSelectValue = (value: string) =>
  value.startsWith(PRESET_PROFILE_VALUE_PREFIX);

export const getPresetProfileBySelectValue = (value: string) =>
  presetProfiles.find((profile) => getPresetProfileSelectValue(profile.key) === value);

export function createPresetProfileAgentForm(profile: PresetProfile): AgentForm {
  const defaults = getDefaultAgentFormValues();
  const fallbackProvider =
    typeof defaults.provider === 'string' ? defaults.provider : (defaults.provider?.value ?? '');
  const providerValue = profile.provider ?? fallbackProvider;
  const modelValue = profile.model ?? defaults.model ?? '';

  return {
    ...defaults,
    agent: {
      label: `Edit Agent Behavior: ${profile.label}`,
      value: getPresetProfileSelectValue(profile.key),
      name: profile.label,
      description: profile.description,
      instructions: profile.instructions,
      provider: providerValue,
      model: modelValue,
    } as TAgentOption,
    id: '',
    name: profile.label,
    description: profile.description,
    instructions: profile.instructions,
    provider: createProviderOption(providerValue),
    model: modelValue,
    model_parameters: profile.model_parameters ?? {},
    category: profile.category ?? defaults.category,
    tools: [],
    tool_options: {},
    recursion_limit: undefined,
  };
}

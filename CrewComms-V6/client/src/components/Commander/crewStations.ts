import { Constants, EModelEndpoint } from 'librechat-data-provider';
import type { Agent, TConversation } from 'librechat-data-provider';

export type CrewStation = {
  id: string;
  name: string;
  state: string;
  endpoint: string;
  endpointType: string;
  model: string;
  agentId?: string;
  runtime: string;
  lease: string;
  dot: string;
  accent: string;
  promptPrefix?: string;
};

const crewPrompt = ({
  name,
  lane,
  rules,
}: {
  name: string;
  lane: string;
  rules: string;
}) => `You are the ${name} lane in the CrewComms stack.

Active crew lane: ${lane}.

The operator's directions are the source of truth unless a hard safety limit or unavailable tool blocks the request.

Lane rules:
${rules}

Operational rules:
1. Start by naming the lane you are taking.
2. State the next action in one short sentence.
3. If blocked, name the blocker plainly.
4. Do not claim tool work, dispatch, file edits, or runtime actions are complete unless they actually happened.
5. Keep the response focused on execution and crew coordination.`;

export const crewStations: CrewStation[] = [
  {
    id: 'silvia',
    name: 'Command',
    state: 'Operator coordination',
    endpoint: 'Ollama-Local',
    endpointType: 'custom',
    model: 'silvia:locutous',
    runtime: 'Ollama local',
    lease: 'none / fast',
    accent: 'from-[#2f7fff] via-[#74adff] to-[#dbe9ff]',
    dot: 'bg-[#74adff]',
    promptPrefix: crewPrompt({
      name: 'command',
      lane: 'operator coordination',
      rules:
        '- Receive operator intent, classify the task lane, preserve artifact context, and choose whether work stays local or routes to another lane.\n- Prefer clarification, triage, policy checks, artifact intake, and routing decisions.\n- Do not silently escalate to execution lanes.',
    }),
  },
  {
    id: 'gem',
    name: 'Primary',
    state: 'Primary orchestration',
    endpoint: 'Local-Bridge',
    endpointType: 'custom',
    model: 'gem',
    runtime: 'Local-Bridge :11436',
    lease: 'fast',
    accent: 'from-[#2f7fff] via-[#74adff] to-[#dbe9ff]',
    dot: 'bg-[#74adff]',
    promptPrefix: crewPrompt({
      name: 'primary orchestration',
      lane: 'primary local orchestration',
      rules:
        '- Receive operator intent, keep chat responsive, and decide whether work stays in the primary lane or routes to control or deep-work lanes.\n- Keep the style direct and clean while preserving operational discipline.\n- Treat the planning lane as secondary and reserved for explicit planning or orchestration work.',
    }),
  },
  {
    id: 'master',
    name: 'Control',
    state: 'Fast local control',
    endpoint: 'Local-Bridge',
    endpointType: 'custom',
    model: 'master',
    runtime: 'Local-Bridge :11436',
    lease: 'fast',
    accent: 'from-[#2f7fff] via-[#74adff] to-[#dbe9ff]',
    dot: 'bg-[#74adff]',
    promptPrefix: crewPrompt({
      name: 'control',
      lane: 'fast local control',
      rules:
        '- Keep chat responsive, clarify operator intent, and route heavy technical work to the deep-work lane.\n- Use concise control-plane language.\n- Do not claim downstream work is complete unless a result actually returned.',
    }),
  },
  {
    id: 'blaster',
    name: 'Deep Work',
    state: 'Deep technical execution',
    endpoint: 'Local-Bridge',
    endpointType: 'custom',
    model: 'blaster',
    runtime: 'Local-Bridge :11436',
    lease: 'deep',
    accent: 'from-[#2f7fff] via-[#74adff] to-[#dbe9ff]',
    dot: 'bg-[#74adff]',
    promptPrefix: crewPrompt({
      name: 'deep work',
      lane: 'deep technical work',
      rules:
        '- Take hard technical execution, careful debugging, and deeper reasoning tasks.\n- Use the Locutous codestral:22b worker path through the bridge runtime.\n- Return results tied to the operator request and distinguish analysis from completed action.',
    }),
  },
  {
    id: 'monty',
    name: 'Planner',
    state: 'Secondary planning lane',
    endpoint: 'Local-Bridge',
    endpointType: 'custom',
    model: 'monty',
    runtime: 'Local-Bridge :11436',
    lease: 'fast',
    accent: 'from-[#2f7fff] via-[#74adff] to-[#dbe9ff]',
    dot: 'bg-[#74adff]',
    promptPrefix: crewPrompt({
      name: 'planning',
      lane: 'secondary orchestration',
      rules:
        '- Support the primary lane when explicitly selected, but do not present yourself as the default lane.\n- Keep planning responsive and call out missing inputs early.\n- Preserve future orchestration handoff notes.',
    }),
  },
  {
    id: 'arc',
    name: 'Routing',
    state: 'Orchestration support',
    endpoint: 'Ollama-Local',
    endpointType: 'custom',
    model: 'arc:locutous',
    runtime: 'Ollama local',
    lease: 'fast',
    accent: 'from-[#2f7fff] via-[#74adff] to-[#dbe9ff]',
    dot: 'bg-[#74adff]',
    promptPrefix: crewPrompt({
      name: 'routing',
      lane: 'orchestration support',
      rules:
        '- Support routing, coordination, and multi-step operational structure.\n- Keep handoffs precise and preserve the return path for results.\n- Prefer structured next actions over broad commentary.',
    }),
  },
  {
    id: 'ark',
    name: 'Research',
    state: 'Research and archive support',
    endpoint: 'Ollama-Local',
    endpointType: 'custom',
    model: 'ark:latest',
    runtime: 'Ollama local',
    lease: 'fast',
    accent: 'from-[#2f7fff] via-[#74adff] to-[#dbe9ff]',
    dot: 'bg-[#74adff]',
    promptPrefix: crewPrompt({
      name: 'research',
      lane: 'archive and research',
      rules:
        '- Organize context, records, and retrieval-style findings.\n- Separate known facts from inference.\n- Keep summaries useful for crew handoff and later verification.',
    }),
  },
];

export function createAgentCrewStation(agent: Agent, index: number): CrewStation {
  const model = agent.model ?? '';
  return {
    id: `agent:${agent.id}`,
    name: `Custom Assistant ${index + 1}`,
    state: 'Configured assistant',
    endpoint: EModelEndpoint.agents,
    endpointType: EModelEndpoint.agents,
    model,
    agentId: agent.id,
    runtime: agent.provider ? `Assistant / ${agent.provider}` : 'Configured assistant',
    lease: 'agent',
    accent: 'from-[#2f7fff] via-[#74adff] to-[#dbe9ff]',
    dot: 'bg-[#74adff]',
  };
}

export function getCrewStationForConversation(
  conversation: TConversation | null,
  stations: CrewStation[] = crewStations,
) {
  return (
    stations.find((station) => {
      if (station.agentId) {
        return (
          conversation?.endpoint === EModelEndpoint.agents &&
          conversation?.agent_id === station.agentId
        );
      }

      return (
        station.endpoint === conversation?.endpoint &&
        station.endpointType === conversation?.endpointType &&
        station.model === conversation?.model
      );
    }) ?? stations[0]
  );
}

export function applyCrewStation(
  conversation: TConversation | null,
  station: CrewStation,
): TConversation {
  const agentSettings = station.agentId
    ? {
        agent_id: station.agentId,
      }
    : {
        agent_id: undefined,
      };

  return {
    ...(conversation ?? {
      conversationId: Constants.NEW_CONVO as string,
      title: 'New Chat',
      createdAt: '',
      updatedAt: '',
    }),
    endpoint: station.endpoint,
    endpointType: station.endpointType,
    model: station.model,
    modelLabel: station.name,
    promptPrefix: station.promptPrefix,
    ...agentSettings,
  };
}

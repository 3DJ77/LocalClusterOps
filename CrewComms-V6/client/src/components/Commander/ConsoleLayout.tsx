import { useMemo } from 'react';
import type { ReactNode } from 'react';
import { SidePanelGroup } from '~/components/SidePanel';
import { useAgentsMapContext, useChatContext } from '~/Providers';
import { cn } from '~/utils';
import {
  applyRoleStation,
  createAgentRoleStation,
  getRoleStationForConversation,
  roleStations,
} from './roleStations';

interface ConsoleLayoutProps {
  artifacts: ReactNode | null;
  children: ReactNode;
}

const labels = {
  dock: 'Role Dock',
  consoleTitle: 'Role Console',
  active: 'Active Role',
  lease: 'lease',
  roster: 'Built-in roles and saved assistants',
  agentCount: 'saved',
  status: 'Status',
  ollamaStatus: 'Ollama local: host confirmed',
  artifacts: 'Artifacts',
  artifactStatus: 'Drawer ready for files, generated work, and handoff notes',
  intake: 'Drop files or images for intake',
};

export default function ConsoleLayout({ artifacts, children }: ConsoleLayoutProps) {
  const { conversation, setConversation } = useChatContext();
  const agentsMap = useAgentsMapContext();
  const agentStations = useMemo(
    () =>
      Object.values(agentsMap ?? {})
        .filter((agent) => agent != null)
        .map((agent, index) => createAgentRoleStation(agent, index)),
    [agentsMap],
  );
  const dockStations = useMemo(() => [...roleStations, ...agentStations], [agentStations]);
  const activeStation = getRoleStationForConversation(conversation, dockStations);

  return (
    <div className="relative isolate grid h-full w-full grid-cols-[minmax(0,1fr)_18rem] grid-rows-[minmax(0,1fr)_6.25rem] overflow-hidden bg-transparent max-lg:grid-cols-1 max-lg:grid-rows-[minmax(0,1fr)_auto_auto]">
      <div aria-hidden="true" className="pointer-events-none absolute inset-0">
        <div
          className="absolute inset-0 opacity-30"
          style={{
            backgroundImage:
              'linear-gradient(rgba(116, 173, 255, 0.11) 1px, transparent 1px), linear-gradient(90deg, rgba(116, 173, 255, 0.11) 1px, transparent 1px)',
            backgroundSize: '3rem 3rem',
          }}
        />
      </div>
      <section
        className="relative min-h-0 min-w-0 overflow-hidden border-r border-[#1b3766] bg-[#001f4b] max-lg:border-b max-lg:border-r-0"
        aria-label="Primary conversation"
      >
        <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-[#2f7fff]" />
        <SidePanelGroup artifacts={artifacts}>
          <main className="flex h-full flex-col overflow-y-auto" role="main">
            {children}
          </main>
        </SidePanelGroup>
      </section>

      <aside
        className="relative flex min-h-0 flex-col overflow-hidden border-[#1b3766] bg-[#061d42] px-3 py-3 shadow-[inset_1px_0_0_rgba(116,173,255,0.18)] max-lg:max-h-[24rem] max-lg:border-t lg:border-l"
        aria-label="System dock"
      >
        <div className="mb-3 shrink-0">
          <p className="text-xs font-semibold uppercase tracking-normal text-[#74adff]">
            {labels.dock}
          </p>
          <h2 className="text-lg font-semibold text-[#dbe9ff]">{labels.consoleTitle}</h2>
          <div className="mt-2 rounded border border-[#274b7d] bg-[#092a5a] px-3 py-2">
            <p className="text-xs font-semibold uppercase tracking-normal text-[#74adff]">
              {labels.active}
            </p>
            <p className="mt-1 text-sm text-[#dbe9ff]">{activeStation.name}</p>
            <p className="mt-0.5 truncate text-xs text-[#9fb4d4]">{activeStation.runtime}</p>
          </div>
          <div className="mt-2 flex items-center justify-between text-xs text-[#9fb4d4]">
            <span>{labels.roster}</span>
            <span>
              {agentStations.length} {labels.agentCount}
            </span>
          </div>
        </div>
        <div
          className="min-h-0 flex-1 space-y-2 overflow-y-auto pr-1"
          role="listbox"
          aria-label="System lane"
        >
          {dockStations.map((station) => (
            <button
              key={station.id}
              type="button"
              aria-pressed={activeStation.id === station.id}
              onClick={() => setConversation((prev) => applyRoleStation(prev, station))}
              className={cn(
                'relative w-full overflow-hidden rounded border px-2.5 py-2 text-left shadow-[0_6px_14px_rgba(0,10,30,0.18)] transition-colors',
                activeStation.id === station.id
                  ? 'border-[#77a8f7] bg-[#123c74]'
                  : 'border-[#274b7d] bg-[#092a5a] hover:border-[#3b6fb3] hover:bg-[#0d356b]',
              )}
            >
              <div className={`absolute inset-x-0 top-0 h-px bg-gradient-to-r ${station.accent}`} />
              <div className="flex items-center justify-between gap-3">
                <span className="font-medium text-[#dbe9ff]">{station.name}</span>
                <span
                  className={cn(
                    'h-2.5 w-2.5 shrink-0 rounded-full shadow-[0_0_18px_currentColor]',
                    station.dot,
                    activeStation.id === station.id && 'ring-2 ring-[#dbe9ff]',
                  )}
                />
              </div>
              <p className="mt-0.5 truncate text-xs text-[#9fb4d4]">{station.state}</p>
              <p className="mt-1 truncate text-xs text-[#dbe9ff]">{station.runtime}</p>
              <p className="mt-0.5 truncate text-xs text-[#9fb4d4]">{labels.lease} {station.lease}</p>
            </button>
          ))}
        </div>
      </aside>

      <footer className="col-span-2 grid min-h-0 grid-cols-[1fr_1.2fr_1fr] gap-3 border-t border-[#1b3766] bg-[#061d42] px-4 py-3 text-sm max-lg:col-span-1 max-lg:grid-cols-1">
        <section
          className="min-w-0 rounded-lg border border-[#274b7d] bg-[#092a5a] p-3 shadow-[0_8px_20px_rgba(0,10,30,0.18)]"
          aria-label="Machine status"
        >
          <p className="text-xs font-semibold uppercase tracking-normal text-[#74adff]">
            {labels.status}
          </p>
          <p className="mt-1 truncate text-[#dbe9ff]">{labels.ollamaStatus}</p>
        </section>
        <section
          className="min-w-0 rounded-lg border border-[#274b7d] bg-[#092a5a] p-3 shadow-[0_8px_20px_rgba(0,10,30,0.18)]"
          aria-label="Artifact drawer"
        >
          <p className="text-xs font-semibold uppercase tracking-normal text-[#74adff]">
            {labels.artifacts}
          </p>
          <p className="mt-1 truncate text-[#dbe9ff]">{labels.artifactStatus}</p>
        </section>
        <section
          className="flex min-h-[3.5rem] items-center justify-center rounded-lg border border-dashed border-[#3b6fb3] bg-[#0d356b] px-3 text-center text-[#dbe9ff] shadow-[0_8px_20px_rgba(0,10,30,0.18)]"
          aria-label="Drop-box intake"
        >
          {labels.intake}
        </section>
      </footer>
    </div>
  );
}

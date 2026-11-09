import AgentsControlPanel from "@/components/AgentsControlPanel";

export default function AgentsPage() {
  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-bold">Autonomous Agents</h1>
        <p className="text-gray-400">
          Manage your AI trading agents, monitor their analysis, and approve executed trades.
        </p>
      </div>

      <AgentsControlPanel />
    </div>
  );
}

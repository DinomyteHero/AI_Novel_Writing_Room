const colors: Record<string, string> = {
  idle: "bg-gray-200 text-gray-700",
  running: "bg-green-100 text-green-800",
  paused: "bg-yellow-100 text-yellow-800",
  milestone_pending: "bg-purple-100 text-purple-800",
  completed: "bg-blue-100 text-blue-800",
  failed: "bg-red-100 text-red-800",
};

export default function StatusBadge({ state }: { state: string }) {
  const cls = colors[state] || colors.idle;
  return (
    <span className={`inline-block px-2 py-1 rounded text-xs font-medium ${cls}`}>
      {state.replace("_", " ")}
    </span>
  );
}

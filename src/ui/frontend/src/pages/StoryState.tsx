import { useQuery } from "@tanstack/react-query";
import { getCharacters, getPlotThreads, getChekovGuns, getDramaticIrony } from "../api/client";

export default function StoryState() {
  const charsQ = useQuery({ queryKey: ["characters"], queryFn: getCharacters });
  const threadsQ = useQuery({ queryKey: ["plot-threads"], queryFn: getPlotThreads });
  const gunsQ = useQuery({ queryKey: ["chekhov-guns"], queryFn: getChekovGuns });
  const ironyQ = useQuery({
    queryKey: ["dramatic-irony"],
    queryFn: () => getDramaticIrony(1),
    retry: false,
  });

  const characters = charsQ.data?.characters ?? [];
  const threads = threadsQ.data?.plot_threads ?? [];
  const guns = gunsQ.data?.chekhov_guns ?? [];
  const ironies = ironyQ.data?.dramatic_ironies ?? [];

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Story State</h2>

      {/* Character Cards */}
      <div>
        <h3 className="font-semibold mb-3">Characters</h3>
        {characters.length === 0 ? (
          <p className="text-gray-400 text-sm">No characters loaded. Start with Phase 2+.</p>
        ) : (
          <div className="grid grid-cols-3 gap-4">
            {characters.map((ch) => (
              <div key={ch.id} className="bg-white rounded-lg shadow p-4">
                <h4 className="font-bold">{ch.name}</h4>
                <div className="text-sm text-gray-600 space-y-1 mt-2">
                  {ch.current_location && <p>Location: {ch.current_location}</p>}
                  {ch.emotional_state && <p>Emotional: {ch.emotional_state}</p>}
                  {ch.arc_position && <p>Arc: {ch.arc_position}</p>}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Plot Threads */}
      <div className="bg-white rounded-lg shadow">
        <div className="p-4 border-b">
          <h3 className="font-semibold">Plot Threads</h3>
        </div>
        {threads.length === 0 ? (
          <p className="p-4 text-gray-400 text-sm">No plot threads.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 text-left">
                <th className="px-4 py-2">Thread</th>
                <th className="px-4 py-2">Status</th>
                <th className="px-4 py-2">Urgency</th>
                <th className="px-4 py-2">Planted</th>
              </tr>
            </thead>
            <tbody>
              {threads.map((t) => (
                <tr key={t.id} className="border-t">
                  <td className="px-4 py-2">
                    <span className="font-medium">{t.id}</span>
                    <p className="text-xs text-gray-500">{t.description}</p>
                  </td>
                  <td className="px-4 py-2">
                    <ThreadStatus status={t.status} />
                  </td>
                  <td className="px-4 py-2">
                    <UrgencyBadge urgency={t.urgency} />
                  </td>
                  <td className="px-4 py-2">Ch {t.planted_chapter}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Chekhov's Guns */}
      <div className="bg-white rounded-lg shadow p-4">
        <h3 className="font-semibold mb-3">Chekhov's Guns</h3>
        {guns.length === 0 ? (
          <p className="text-gray-400 text-sm">No Chekhov's guns tracked.</p>
        ) : (
          <ul className="text-sm space-y-2">
            {guns.map((g, i) => (
              <li key={i} className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-yellow-500 shrink-0" />
                <span>{String(g.item_description ?? g.id)}</span>
                <span className="text-xs text-gray-400 ml-auto">
                  Planted Ch {String(g.planted_chapter)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Dramatic Irony */}
      <div className="bg-white rounded-lg shadow p-4">
        <h3 className="font-semibold mb-3">Dramatic Irony</h3>
        {ironies.length === 0 ? (
          <p className="text-gray-400 text-sm">No dramatic irony situations detected.</p>
        ) : (
          <ul className="text-sm space-y-2">
            {ironies.map((irony, i) => (
              <li key={i} className="bg-purple-50 rounded p-2">
                <pre className="text-xs whitespace-pre-wrap">{JSON.stringify(irony, null, 2)}</pre>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

const statusColors: Record<string, string> = {
  planted: "bg-gray-200 text-gray-700",
  active: "bg-blue-100 text-blue-700",
  escalating: "bg-orange-100 text-orange-700",
  resolving: "bg-green-100 text-green-700",
  resolved: "bg-green-200 text-green-800",
};

function ThreadStatus({ status }: { status: string }) {
  const cls = statusColors[status] || statusColors.active;
  return <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${cls}`}>{status}</span>;
}

const urgencyColors: Record<string, string> = {
  background: "text-gray-500",
  rising: "text-yellow-600",
  critical: "text-orange-600",
  climactic: "text-red-600",
};

function UrgencyBadge({ urgency }: { urgency: string }) {
  const cls = urgencyColors[urgency] || "text-gray-500";
  return <span className={`text-xs font-medium ${cls}`}>{urgency}</span>;
}

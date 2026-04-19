import { useEffect, useRef } from "react";
import type { LedgerEvent } from "../api/types";

const typeColors: Record<string, string> = {
  pipeline_start: "text-blue-600",
  pipeline_complete: "text-blue-600",
  chapter_start: "text-indigo-600",
  agent_start: "text-gray-500",
  agent_complete: "text-gray-600",
  // Relay v3 Stage 1i: gate events are telemetry; advisories orange, blockers red.
  gate_pass: "text-green-600",
  gate_fail: "text-orange-600",
  final_gate_complete: "text-teal-600",
  final_gate_rejection: "text-orange-600",
  compression_guard_fired: "text-orange-600",
  continuity_editor_complete: "text-teal-600",
  pov_advisory: "text-orange-600",
  chapter_word_count_telemetry: "text-gray-600",
  save_blocked: "text-red-700 font-semibold",
  milestone_reached: "text-purple-600",
  milestone_gate_paused: "text-purple-700",
};

// Icon hints shown before the event name for high-salience events. Uses
// text glyphs (no emoji) so the monospace column remains aligned.
const typeIcons: Record<string, string> = {
  save_blocked: "[!] ",
  pov_advisory: "[~] ",
  compression_guard_fired: "[~] ",
  final_gate_rejection: "[~] ",
  gate_fail: "[~] ",
  gate_pass: "[+] ",
  continuity_editor_complete: "[+] ",
};

// Saved-scene status vocabulary (matches the three-value enum from the
// relay v3 status migration: saved_clean / saved_with_advisory / quarantined).
export const statusColors: Record<string, string> = {
  saved_clean: "text-green-600",
  saved_with_advisory: "text-orange-600",
  quarantined: "text-red-700 font-semibold",
  // Pre-save state — rendered neutrally.
  draft: "text-gray-500",
  // Legacy shims, kept for transition-period backcompat so UI doesn't blank
  // out on older ledger rows a viewer happens to load. Retire after a cycle.
  pass: "text-green-600",
  advisory: "text-orange-600",
};

export default function EventLog({ events }: { events: LedgerEvent[] }) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events.length]);

  if (events.length === 0) {
    return (
      <div className="text-gray-400 text-sm p-4">No events yet. Start a pipeline run.</div>
    );
  }

  return (
    <div className="h-80 overflow-y-auto font-mono text-xs space-y-0.5 bg-gray-50 rounded p-2">
      {events.map((ev) => {
        const time = new Date(ev.timestamp).toLocaleTimeString();
        const color = typeColors[ev.event_type] || "text-gray-600";
        const icon = typeIcons[ev.event_type] ?? "";
        return (
          <div key={ev.id} className="flex gap-2">
            <span className="text-gray-400 w-20 shrink-0">{time}</span>
            <span className={`${color} w-44 shrink-0 truncate`}>{icon}{ev.event_type}</span>
            {ev.chapter_number != null && (
              <span className="text-gray-500">
                Ch{ev.chapter_number}.{ev.scene_number ?? 1}
              </span>
            )}
            {ev.agent_role && <span className="text-gray-400">[{ev.agent_role}]</span>}
          </div>
        );
      })}
      <div ref={endRef} />
    </div>
  );
}

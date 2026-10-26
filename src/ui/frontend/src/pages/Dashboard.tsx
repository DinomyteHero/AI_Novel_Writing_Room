import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { getChapters, getManuscriptSummary } from "../api/client";

export default function Dashboard() {
  const chapters = useQuery({
    queryKey: ["chapters"],
    queryFn: getChapters,
    refetchInterval: 5000,
  });

  const manuscript = useQuery({
    queryKey: ["manuscript-summary"],
    queryFn: getManuscriptSummary,
    refetchInterval: 10000,
  });

  const chList = chapters.data?.chapters ?? [];
  const ms = manuscript.data;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold">Book</h2>
        <p className="text-sm text-gray-500 mt-1">
          Saved chapters from the current run. Use the CLI to draft or export.
        </p>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <StatCard label="Total Words" value={ms?.total_word_count?.toLocaleString() ?? "0"} />
        <StatCard label="Chapters" value={String(ms?.chapter_count ?? 0)} />
        <StatCard label="Scenes" value={String(chList.length)} />
      </div>

      <div className="bg-white rounded-lg shadow">
        <div className="p-4 border-b">
          <h3 className="font-semibold">Chapters</h3>
        </div>
        {chList.length === 0 ? (
          <p className="p-4 text-gray-400 text-sm">
            No chapter prose found. Run the pipeline from the CLI first.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 text-left">
                  <th className="px-4 py-2">Chapter</th>
                  <th className="px-4 py-2">Scene</th>
                  <th className="px-4 py-2">Words</th>
                  <th className="px-4 py-2" />
                </tr>
              </thead>
              <tbody>
                {chList.map((ch) => (
                  <tr key={`${ch.chapter_number}-${ch.scene_number}`} className="border-t hover:bg-gray-50">
                    <td className="px-4 py-2">{ch.chapter_number}</td>
                    <td className="px-4 py-2">{ch.scene_number}</td>
                    <td className="px-4 py-2">{ch.word_count.toLocaleString()}</td>
                    <td className="px-4 py-2">
                      <Link
                        to={`/chapters/${ch.chapter_number}/${ch.scene_number}`}
                        className="text-blue-600 hover:underline text-xs"
                      >
                        Read
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-white rounded-lg shadow p-4">
      <p className="text-xs text-gray-500 uppercase tracking-wide">{label}</p>
      <p className="text-2xl font-bold mt-1">{value}</p>
    </div>
  );
}

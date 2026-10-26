import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getChapter } from "../api/client";

export default function ChapterViewer() {
  const { chapter, scene } = useParams<{ chapter: string; scene: string }>();
  const ch = Number(chapter);
  const sc = Number(scene);

  const chapterQ = useQuery({
    queryKey: ["chapter", ch, sc],
    queryFn: () => getChapter(ch, sc),
    enabled: !isNaN(ch) && !isNaN(sc),
  });

  const data = chapterQ.data;

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Link to="/" className="text-blue-600 hover:underline text-sm">&larr; Book</Link>
        <h2 className="text-2xl font-bold">
          Chapter {ch}, Scene {sc}
        </h2>
        {data && (
          <span className="text-sm text-gray-500">{data.word_count.toLocaleString()} words</span>
        )}
      </div>

      <div className="bg-white rounded-lg shadow p-6 max-w-4xl">
        {chapterQ.isLoading && <p className="text-gray-400">Loading...</p>}
        {chapterQ.error && (
          <p className="text-red-600">Failed to load chapter: {String(chapterQ.error)}</p>
        )}
        {data && (
          <div className="prose prose-sm max-w-none">
            {data.prose.split("\n\n").map((para, i) => (
              <p key={i} className="mb-3 leading-relaxed">
                <span className="text-xs text-gray-300 mr-2">{i + 1}</span>
                {para}
              </p>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

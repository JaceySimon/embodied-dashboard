import { loadPapers } from "@/lib/data";

export default async function SearchPage({
  searchParams,
}: {
  searchParams: { q?: string; tag?: string };
}) {
  const papers = loadPapers();
  const q = searchParams.q?.toLowerCase() || "";
  const tag = searchParams.tag || "";

  const filtered = papers.filter((p) => {
    const matchQ = !q || p.title.toLowerCase().includes(q) || p.abstract?.toLowerCase().includes(q);
    const matchTag = !tag || p.tags.includes(tag);
    return matchQ && matchTag;
  });

  return (
    <div>
      <h1 className="text-2xl font-bold text-white mb-4">搜索</h1>
      <div className="space-y-4">
        {filtered.slice(0, 50).map((paper) => (
          <div key={paper.id} className="bg-gray-900 border border-gray-800 rounded-lg p-4">
            <a href={`/papers/${paper.id}`} className="text-lg font-medium text-white hover:text-blue-400">
              {paper.title}
            </a>
            <div className="mt-2 text-sm text-gray-400">
              {paper.authors.slice(0, 3).join(", ")}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

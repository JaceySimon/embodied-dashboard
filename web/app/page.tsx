import { loadPapers } from "@/lib/data";

export default function HomePage() {
  const papers = loadPapers().slice(0, 50);

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-white mb-2">本周新增</h1>
        <p className="text-gray-400">最近 90 天 · {papers.length} 篇论文</p>
      </div>

      <div className="space-y-4">
        {papers.map((paper) => (
          <div key={paper.id} className="bg-gray-900 border border-gray-800 rounded-lg p-4">
            <a href={`/papers/${paper.id}`} className="text-lg font-medium text-white hover:text-blue-400">
              {paper.title}
            </a>
            <div className="mt-2 text-sm text-gray-400">
              {paper.authors.slice(0, 3).join(", ")}
              {paper.authors.length > 3 && " et al."}
            </div>
            <div className="mt-2 flex gap-2 flex-wrap">
              {paper.tags.slice(0, 5).map((tag) => (
                <span key={tag} className="bg-blue-900/50 text-blue-300 px-2 py-0.5 rounded text-xs">
                  {tag}
                </span>
              ))}
            </div>
            <div className="mt-2 text-xs text-gray-500">
              {paper.published_at.slice(0, 10)} · {paper.source_name}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

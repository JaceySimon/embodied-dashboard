import { getPaperById } from "@/lib/data";
import { notFound } from "next/navigation";

export default async function PaperDetailPage({
  params,
}: {
  params: { id: string };
}) {
  const paper = getPaperById(params.id);
  if (!paper) notFound();

  return (
    <div>
      <h1 className="text-2xl font-bold text-white mb-4">{paper.title}</h1>
      <div className="text-gray-400 mb-4">
        {paper.authors.join(", ")} · {paper.published_at.slice(0, 10)}
      </div>
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 mb-4">
        <h2 className="text-lg font-medium text-white mb-2">摘要</h2>
        <p className="text-gray-300">{paper.abstract}</p>
      </div>
      <div className="flex gap-4">
        <a href={paper.url} target="_blank" className="text-blue-400 hover:underline">
          论文原文
        </a>
        {paper.code_url && (
          <a href={paper.code_url} target="_blank" className="text-blue-400 hover:underline">
            代码
          </a>
        )}
      </div>
    </div>
  );
}

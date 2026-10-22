import fs from "fs";
import path from "path";

export interface Paper {
  id: string;
  title: string;
  abstract: string;
  authors: string[];
  url: string;
  published_at: string;
  tags: string[];
  code_url?: string;
  source_name: string;
}

export function loadPapers(): Paper[] {
  // 读取 backfill 数据
  const dataPath = path.join(process.cwd(), "..", "data", "backfill", "arxiv_backfill_90d_20261021.json");
  try {
    const raw = fs.readFileSync(dataPath, "utf-8");
    const papers = JSON.parse(raw);
    return papers.sort((a: Paper, b: Paper) => 
      new Date(b.published_at).getTime() - new Date(a.published_at).getTime()
    );
  } catch {
    return [];
  }
}

export function getPaperById(id: string): Paper | undefined {
  const papers = loadPapers();
  return papers.find(p => p.id === id);
}

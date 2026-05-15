import type { AssistantTool } from "@/lib/useChat";

export function ToolCard({ tool, args }: AssistantTool) {
  return (
    <div className="my-1 rounded-md border border-zinc-200 bg-zinc-50 px-3 py-2 font-mono text-xs text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400">
      <span className="text-emerald-600 dark:text-emerald-400">▸ {tool}</span>
      {args !== undefined && args !== null ? (
        <span className="ml-1 break-all">{JSON.stringify(args)}</span>
      ) : null}
    </div>
  );
}

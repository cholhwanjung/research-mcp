import type { ToolEntry } from "@/lib/chatState";

export function ToolCard({ entry, onUndo }: { entry: ToolEntry; onUndo?: (snapshot: string) => void }) {
  const { tool, args, result, snapshot, restored } = entry;
  return (
    <div className="my-1 rounded-md border border-zinc-200 bg-zinc-50 px-3 py-2 font-mono text-xs text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400">
      <div>
        <span className="text-emerald-600 dark:text-emerald-400">▸ {tool}</span>
        {args !== undefined && args !== null ? <span className="ml-1 break-all">{JSON.stringify(args)}</span> : null}
      </div>
      {result ? <div className="mt-1 line-clamp-3 break-all whitespace-pre-wrap text-zinc-500">{result}</div> : null}
      {snapshot && onUndo ? (
        restored ? (
          <div className="mt-1 text-zinc-500">↩ 되돌림</div>
        ) : (
          <button
            onClick={() => onUndo(snapshot)}
            className="mt-1 rounded border border-zinc-300 px-2 py-0.5 hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
          >
            되돌리기
          </button>
        )
      ) : null}
    </div>
  );
}

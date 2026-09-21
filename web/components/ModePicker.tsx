import { MODES, type Mode } from "@/lib/api";

export function ModePicker({ value, onChange }: { value: Mode; onChange: (v: Mode) => void }) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value as Mode)}
      aria-label="permission mode"
      className="rounded-md border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900"
    >
      {MODES.map((m) => (
        <option key={m.value} value={m.value}>
          {m.label}
        </option>
      ))}
    </select>
  );
}

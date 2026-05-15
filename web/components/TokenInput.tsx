export function TokenInput({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <input
      type="password"
      value={value}
      placeholder="API token (옵션)"
      aria-label="api token"
      onChange={(e) => onChange(e.target.value)}
      className="w-36 rounded-md border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900"
    />
  );
}

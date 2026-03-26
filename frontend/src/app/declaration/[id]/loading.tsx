export default function Loading() {
  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-300 font-sans p-8">
      <div className="max-w-5xl mx-auto space-y-8">
        <div className="h-4 w-32 bg-zinc-800 rounded" />

        {/* Header skeleton */}
        <div className="border-b border-zinc-900 pb-8 animate-pulse">
          <div className="flex justify-between items-start">
            <div className="space-y-3">
              <div className="h-8 w-64 bg-zinc-800 rounded" />
              <div className="h-5 w-48 bg-zinc-800 rounded" />
              <div className="h-4 w-56 bg-zinc-800 rounded" />
            </div>
            <div className="text-right space-y-2">
              <div className="h-4 w-24 bg-zinc-800 rounded ml-auto" />
              <div className="h-10 w-20 bg-zinc-800 rounded ml-auto" />
            </div>
          </div>
        </div>

        {/* Anomaly section skeleton */}
        <div className="animate-pulse">
          <div className="h-6 w-40 bg-zinc-800 rounded mb-4" />
          <div className="bg-zinc-900/50 border border-zinc-800 rounded-xl p-6 space-y-3">
            <div className="h-4 w-full bg-zinc-800 rounded" />
            <div className="h-4 w-3/4 bg-zinc-800 rounded" />
          </div>
        </div>

        {/* Financial summary skeleton */}
        <div className="animate-pulse">
          <div className="h-6 w-48 bg-zinc-800 rounded mb-4" />
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {[1, 2].map((i) => (
              <div
                key={i}
                className="bg-zinc-900/30 border border-zinc-800 rounded-xl p-6 space-y-3"
              >
                <div className="h-4 w-36 bg-zinc-800 rounded" />
                <div className="h-8 w-28 bg-zinc-800 rounded" />
                <div className="h-3 w-24 bg-zinc-800 rounded" />
              </div>
            ))}
          </div>
        </div>

        {/* Table skeleton */}
        <div className="animate-pulse">
          <div className="h-6 w-32 bg-zinc-800 rounded mb-4" />
          <div className="bg-zinc-900/30 border border-zinc-800 rounded-xl overflow-hidden">
            {[1, 2, 3].map((i) => (
              <div
                key={i}
                className="px-6 py-3 border-b border-zinc-800/50 flex gap-6"
              >
                <div className="h-4 w-32 bg-zinc-800 rounded" />
                <div className="h-4 w-48 bg-zinc-800 rounded" />
                <div className="h-4 w-20 bg-zinc-800 rounded ml-auto" />
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function Loading() {
  return (
    <main className="min-h-screen bg-zinc-950 text-zinc-300 font-sans p-8">
      <section className="max-w-7xl mx-auto space-y-12">
        <header className="flex items-end justify-between border-b border-zinc-900 pb-6">
          <div>
            <h1 className="text-3xl font-bold tracking-tight text-zinc-50">
              Project Argus
            </h1>
            <p className="text-zinc-500 mt-2">Loading dashboard data&hellip;</p>
          </div>
        </header>

        {/* Skeleton stats */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {[1, 2, 3].map((i) => (
            <div
              key={i}
              className="bg-zinc-900/50 border border-zinc-800 rounded-xl p-6 animate-pulse"
            >
              <div className="h-4 w-24 bg-zinc-800 rounded mb-3" />
              <div className="h-8 w-16 bg-zinc-800 rounded" />
            </div>
          ))}
        </div>

        {/* Skeleton table */}
        <div className="bg-zinc-900/50 border border-zinc-800 rounded-xl overflow-hidden">
          <div className="bg-zinc-900 px-6 py-4 border-b border-zinc-800">
            <div className="h-4 w-48 bg-zinc-800 rounded" />
          </div>
          {[1, 2, 3, 4, 5].map((i) => (
            <div
              key={i}
              className="px-6 py-4 border-b border-zinc-800/50 flex gap-6 animate-pulse"
            >
              <div className="h-4 w-32 bg-zinc-800 rounded" />
              <div className="h-4 w-48 bg-zinc-800 rounded" />
              <div className="h-4 w-20 bg-zinc-800 rounded ml-auto" />
              <div className="h-4 w-16 bg-zinc-800 rounded" />
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}

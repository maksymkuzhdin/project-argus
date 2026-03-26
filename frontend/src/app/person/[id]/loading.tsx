export default function PersonTimelineLoading() {
  return (
    <main className="min-h-screen bg-zinc-950 text-zinc-300 font-sans p-8">
      <section className="max-w-6xl mx-auto space-y-6">
        <div className="h-4 w-44 bg-zinc-800 rounded animate-pulse" />
        <div className="h-10 w-80 bg-zinc-800 rounded animate-pulse" />
        <div className="bg-zinc-900/50 border border-zinc-800 rounded-xl p-6 animate-pulse">
          <div className="h-6 w-40 bg-zinc-800 rounded mb-4" />
          <div className="h-10 w-24 bg-zinc-800 rounded" />
        </div>
        <div className="bg-zinc-900/50 border border-zinc-800 rounded-xl p-6 animate-pulse h-56" />
      </section>
    </main>
  );
}

import Link from "next/link";
import DeclarationDetail from "./[id]/page";

export const revalidate = 0;

export default async function DeclarationByQuery({
  searchParams,
}: {
  searchParams: Promise<{ id?: string; returnTo?: string }>;
}) {
  const resolved = await searchParams;
  const id = resolved.id;
  const returnTo = resolved.returnTo;

  if (!id) {
    return (
      <main className="min-h-screen bg-zinc-950 text-zinc-300 font-sans p-8">
        <div className="max-w-5xl mx-auto space-y-4">
          <Link href="/" className="text-sm text-zinc-500 hover:text-zinc-300">
            &larr; Back to Dashboard
          </Link>
          <div className="bg-zinc-900/50 border border-zinc-800 rounded-xl p-6">
            <h1 className="text-xl font-semibold text-zinc-100">Missing declaration ID</h1>
            <p className="text-zinc-400 mt-2">Open a declaration from the dashboard table.</p>
          </div>
        </div>
      </main>
    );
  }

  return DeclarationDetail({
    params: Promise.resolve({ id }),
    searchParams: Promise.resolve({ returnTo }),
  });
}

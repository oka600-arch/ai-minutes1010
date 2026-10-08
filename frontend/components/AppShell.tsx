"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { getSupabase } from "@/lib/supabase";

/** ログイン必須の画面を包むレイアウト。未ログインならログイン画面へ移動する */
export function AppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [email, setEmail] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [configError, setConfigError] = useState<string | null>(null);

  useEffect(() => {
    let supabase;
    try {
      supabase = getSupabase();
    } catch (e) {
      setConfigError((e as Error).message);
      return;
    }
    supabase.auth.getSession().then(({ data }) => {
      if (!data.session) {
        router.replace("/login");
        return;
      }
      setEmail(data.session.user.email ?? null);
      setReady(true);
    });
    const { data: sub } = supabase.auth.onAuthStateChange((_event, session) => {
      if (!session) router.replace("/login");
    });
    return () => sub.subscription.unsubscribe();
  }, [router]);

  async function logout() {
    await getSupabase().auth.signOut();
    router.replace("/login");
  }

  if (configError) {
    return <div className="m-6 rounded border border-red-200 bg-red-50 p-4 text-sm text-red-800">{configError}</div>;
  }
  if (!ready) return <div className="p-10 text-center text-sm text-gray-500">読み込み中…</div>;

  const nav = [
    { href: "/", label: "ダッシュボード" },
    { href: "/settings", label: "設定" },
  ];

  return (
    <div className="min-h-screen">
      <header className="border-b border-gray-200 bg-white">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-2 px-4 py-3">
          <Link href="/" className="text-base font-bold text-brand-700">
            AI議事録システム
          </Link>
          <nav className="flex items-center gap-1 text-sm">
            {nav.map((n) => (
              <Link
                key={n.href}
                href={n.href}
                className={`rounded px-3 py-1.5 ${pathname === n.href ? "bg-brand-50 font-semibold text-brand-700" : "text-gray-600 hover:bg-gray-100"}`}
              >
                {n.label}
              </Link>
            ))}
            <span className="hidden px-2 text-xs text-gray-400 sm:inline">{email}</span>
            <button onClick={logout} className="rounded px-3 py-1.5 text-gray-600 hover:bg-gray-100">
              ログアウト
            </button>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-4 py-6">{children}</main>
    </div>
  );
}

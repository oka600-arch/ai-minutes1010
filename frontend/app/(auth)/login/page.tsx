"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Alert, Button, Field, inputClass } from "@/components/ui";
import { getSupabase } from "@/lib/supabase";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const { error } = await getSupabase().auth.signInWithPassword({ email, password });
      if (error) {
        setError("メールアドレスまたはパスワードが正しくありません。");
        return;
      }
      router.replace("/");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <Field label="メールアドレス">
        <input type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} className={inputClass} />
      </Field>
      <Field label="パスワード">
        <input
          type="password"
          required
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className={inputClass}
        />
      </Field>
      {error && <Alert>{error}</Alert>}
      <Button type="submit" disabled={loading} className="w-full">
        {loading ? "ログイン中…" : "ログイン"}
      </Button>
      <p className="text-center text-sm">
        <Link href="/signup" className="text-brand-600 hover:underline">
          アカウント登録
        </Link>
      </p>
    </form>
  );
}

"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Alert, Button, Field, inputClass } from "@/components/ui";
import { getSupabase } from "@/lib/supabase";

export default function SignupPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (password.length < 8) {
      setError("パスワードは8文字以上にしてください。");
      return;
    }
    setLoading(true);
    try {
      const { data, error } = await getSupabase().auth.signUp({ email, password, options: { data: { name } } });
      if (error) {
        setError("アカウントを登録できませんでした。すでに登録済みのメールアドレスでないか確認してください。");
        return;
      }
      if (data.session) {
        router.replace("/");
      } else {
        setInfo("確認メールを送信しました。メール内のリンクを開いてからログインしてください。");
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <h2 className="text-base font-bold">アカウント登録</h2>
      <Field label="氏名">
        <input required value={name} onChange={(e) => setName(e.target.value)} className={inputClass} />
      </Field>
      <Field label="メールアドレス">
        <input type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} className={inputClass} />
      </Field>
      <Field label="パスワード" hint="8文字以上">
        <input
          type="password"
          required
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className={inputClass}
        />
      </Field>
      {error && <Alert>{error}</Alert>}
      {info && <Alert kind="success">{info}</Alert>}
      <Button type="submit" disabled={loading} className="w-full">
        {loading ? "登録中…" : "登録する"}
      </Button>
      <p className="text-center text-sm">
        <Link href="/login" className="text-brand-600 hover:underline">
          ログイン画面へ戻る
        </Link>
      </p>
    </form>
  );
}

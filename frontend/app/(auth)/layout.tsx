export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center px-4 py-10">
      <div className="w-full max-w-sm">
        <h1 className="mb-6 text-center text-xl font-bold text-brand-700">AI議事録システム</h1>
        <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm">{children}</div>
      </div>
    </div>
  );
}

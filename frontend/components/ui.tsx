// 共通の小さな UI 部品

export function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <section className={`rounded-lg border border-gray-200 bg-white p-5 shadow-sm ${className}`}>{children}</section>;
}

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger" };

export function Button({ variant = "primary", className = "", ...props }: ButtonProps) {
  const styles = {
    primary: "bg-brand-700 text-white hover:bg-brand-800 disabled:bg-gray-300",
    secondary: "border border-gray-300 bg-white text-gray-700 hover:bg-gray-50 disabled:text-gray-400",
    danger: "border border-red-300 bg-white text-red-700 hover:bg-red-50",
  }[variant];
  return (
    <button
      {...props}
      className={`inline-flex items-center justify-center rounded-md px-4 py-2 text-sm font-semibold transition-colors disabled:cursor-not-allowed ${styles} ${className}`}
    />
  );
}

export function Alert({ kind = "error", children }: { kind?: "error" | "info" | "success"; children: React.ReactNode }) {
  const styles = {
    error: "border-red-200 bg-red-50 text-red-800",
    info: "border-brand-100 bg-brand-50 text-brand-800",
    success: "border-green-200 bg-green-50 text-green-800",
  }[kind];
  return (
    <div role={kind === "error" ? "alert" : "status"} className={`rounded-md border px-4 py-3 text-sm ${styles}`}>
      {children}
    </div>
  );
}

export function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-semibold text-gray-700">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-gray-500">{hint}</span>}
    </label>
  );
}

export const inputClass =
  "w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus:border-brand-600 focus:outline-none focus:ring-2 focus:ring-brand-100";

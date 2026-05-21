"use client";

import { useRouter } from "next/navigation";
import { AuthForm } from "@/components/AuthForm";
import type { AuthLocale } from "@/lib/auth-locale";

interface RegisterClientProps {
  initialLocale?: AuthLocale;
}

export function RegisterClient({ initialLocale }: RegisterClientProps) {
  const router = useRouter();

  return (
    <main className="container auth-page">
      <AuthForm
        mode="register"
        initialLocale={initialLocale}
        onSuccess={() => router.replace("/dashboard")}
      />
    </main>
  );
}
